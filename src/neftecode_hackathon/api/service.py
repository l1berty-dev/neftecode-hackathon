"""Application services shared by CLI and FastAPI."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from neftecode_hackathon.api.models import (
    ControlResponse,
    ControlsResponse,
    DecisionListResponse,
    DecisionResponse,
    DecisionSummary,
    EpisodeResponse,
    EpisodesResponse,
    ModelledPresetsResponse,
    ModelledRunResponse,
    ModelledRunsResponse,
    SaveDecisionResponse,
    ScenarioResponse,
    SnapshotResponse,
    StoredDecisionResponse,
)
from neftecode_hackathon.contracts import (
    Action,
    ActionOrigin,
    Decision,
    ModelledChainRequest,
    ProcessSnapshot,
)
from neftecode_hackathon.data import (
    ReplayCatalogue,
    SnapshotProvider,
    load_replay_catalogue,
)
from neftecode_hackathon.modelled import ModelledChainEngine, build_presets
from neftecode_hackathon.orchestration import Coordinator
from neftecode_hackathon.persistence import (
    CalculationRepository,
    DecisionRepository,
    EvaluationRepository,
    ModelledRunRepository,
    ReplayConflictError,
    ReplayRepository,
    SnapshotRepository,
)
from neftecode_hackathon.quality import ForecastQualityAgent
from neftecode_hackathon.reliability import SeverityProxyAgent
from neftecode_hackathon.scenarios import ScenarioEvaluator
from neftecode_hackathon.scenarios.config import (
    ScenarioPolicy,
    load_policy,
    load_ranking_policy,
    load_severity_policy,
)


class ApplicationError(RuntimeError):
    status_code = 500
    code = "application_error"

    def __init__(self, message: str, details=None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(ApplicationError):
    status_code = 404
    code = "not_found"


class RequestError(ApplicationError):
    status_code = 422
    code = "invalid_request"


class ConflictError(ApplicationError):
    status_code = 409
    code = "state_conflict"


class NotReadyError(ApplicationError):
    status_code = 503
    code = "not_ready"


@dataclass(frozen=True)
class CalculationRuntime:
    snapshot_provider: SnapshotProvider
    quality_agent: ForecastQualityAgent
    policy: ScenarioPolicy
    evaluator: ScenarioEvaluator
    coordinator: Coordinator
    replay_catalogue: ReplayCatalogue

    def snapshot_at(self, at) -> ProcessSnapshot:
        return self.snapshot_provider.get_snapshot(at)

    def decide_at(self, at) -> Decision:
        return self.coordinator.decide(self.snapshot_at(at), horizon_minutes=60)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def build_calculation_runtime(root: Path | None = None) -> CalculationRuntime:
    root = (root or repository_root()).resolve()
    data_directory = _configured_directory(root, "DATA_DIR", "data/processed")
    model_directory = _configured_directory(root, "MODEL_DIR", "artifacts")
    policy = load_policy(root / "config/controls.yaml", root / "config/constraints.yaml")
    provider = SnapshotProvider.from_repository(
        root, policy=policy, processed_directory=data_directory
    )
    quality_agent = ForecastQualityAgent.from_repository(root, artifacts_directory=model_directory)
    if quality_agent.model_version != policy.constraints.model_version:
        raise ValueError("active model and constraint policy versions differ")
    evaluator = ScenarioEvaluator(
        quality_agent=quality_agent,
        reliability_agent=SeverityProxyAgent(load_severity_policy(root / "config/severity.yaml")),
        model_version=quality_agent.model_version,
        policy=policy,
    )
    catalogue = load_replay_catalogue(root / "config/replay.yaml")
    replay_not_before = datetime.fromisoformat(quality_agent.manifest["replay_not_before"])
    for episode in catalogue.episodes:
        if episode.start < replay_not_before:
            raise ValueError(f"episode {episode.episode_id} precedes replay_not_before")
    return CalculationRuntime(
        snapshot_provider=provider,
        quality_agent=quality_agent,
        policy=policy,
        evaluator=evaluator,
        coordinator=Coordinator(
            evaluator, ranking_policy=load_ranking_policy(root / "config/ranking.yaml")
        ),
        replay_catalogue=catalogue,
    )


def _configured_directory(root: Path, variable: str, default: str) -> Path:
    configured = Path(os.environ.get(variable, default))
    return (configured if configured.is_absolute() else root / configured).resolve()


class ApplicationService:
    def __init__(
        self,
        runtime: CalculationRuntime,
        sessions: sessionmaker[Session],
        modelled_engine: ModelledChainEngine | None = None,
    ) -> None:
        self.runtime = runtime
        self.sessions = sessions
        self.modelled_engine = modelled_engine or ModelledChainEngine.from_repository(
            repository_root()
        )

    @classmethod
    def from_environment(
        cls, runtime: CalculationRuntime | None = None, *, root: Path | None = None
    ) -> ApplicationService:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise NotReadyError(
                "DATABASE_URL is not configured; start PostgreSQL and apply Alembic migrations."
            )
        engine = create_engine(database_url, pool_pre_ping=True)
        resolved_root = (root or repository_root()).resolve()
        service = cls(
            runtime or build_calculation_runtime(resolved_root),
            sessionmaker(engine),
            ModelledChainEngine.from_repository(resolved_root),
        )
        service.check_database()
        return service

    def check_database(self) -> None:
        with self.sessions() as session:
            session.execute(text("SELECT 1"))

    def controls(self) -> ControlsResponse:
        catalogue = self.runtime.policy.catalogue
        return ControlsResponse(
            constraint_version=catalogue.constraint_version,
            controls=tuple(
                ControlResponse(
                    signal_id=control.signal_id,
                    label=control.name,
                    available=control.available,
                    reason=control.unavailable_reason,
                    unit=control.canonical_unit,
                    min=control.model_min,
                    max=control.model_max,
                    step=control.step,
                    source="; ".join(control.evidence),
                )
                for control in catalogue.controls
            ),
            review_issues=catalogue.review_issues,
        )

    def episodes(self) -> EpisodesResponse:
        catalogue = self.runtime.replay_catalogue
        return EpisodesResponse(
            version=catalogue.version,
            episodes=tuple(
                EpisodeResponse(**episode.model_dump()) for episode in catalogue.episodes
            ),
        )

    def start_replay(self, episode_id: str | None) -> SnapshotResponse:
        episode_id = episode_id or self.runtime.replay_catalogue.episodes[0].episode_id
        episode = self.runtime.replay_catalogue.get(episode_id)
        if episode is None:
            raise NotFoundError("Replay episode was not found.", {"episode_id": episode_id})
        snapshot = self.runtime.snapshot_at(episode.start)
        with self.sessions() as session, session.begin():
            SnapshotRepository(session).put(snapshot)
            replay = ReplayRepository(session)
            current = replay.get(for_update=True)
            if current is None:
                replay.initialize(episode_id, snapshot.snapshot_id)
            else:
                replay.restart(episode_id, current.current_snapshot_id, snapshot.snapshot_id)
        return SnapshotResponse(snapshot=snapshot, current_snapshot_id=snapshot.snapshot_id)

    def advance_replay(self, expected_snapshot_id: UUID) -> SnapshotResponse:
        try:
            with self.sessions() as session, session.begin():
                repository = ReplayRepository(session)
                state = repository.get(for_update=True)
                if state is None:
                    raise NotFoundError("Replay has not been started.")
                if state.current_snapshot_id != expected_snapshot_id:
                    raise ReplayConflictError("expected_snapshot_id is stale")
                episode = self.runtime.replay_catalogue.get(state.episode_id)
                if episode is None:
                    raise NotReadyError(
                        "Stored replay episode is absent from the active catalogue."
                    )
                next_position = state.position + 1
                if next_position >= episode.positions:
                    raise ConflictError(
                        "Replay episode is complete.",
                        {"current_snapshot_id": str(state.current_snapshot_id)},
                    )
                snapshot = self.runtime.snapshot_at(episode.timestamp_at(next_position))
                SnapshotRepository(session).put(snapshot)
                repository.advance(
                    state.episode_id, state.current_snapshot_id, snapshot.snapshot_id
                )
        except ReplayConflictError as error:
            current_id = self._read_current_id()
            raise ConflictError(
                "Replay state has already changed.",
                {"current_snapshot_id": str(current_id) if current_id else None},
            ) from error
        return SnapshotResponse(snapshot=snapshot, current_snapshot_id=snapshot.snapshot_id)

    def current_snapshot(self) -> SnapshotResponse:
        with self.sessions() as session:
            state = ReplayRepository(session).get()
            if state is None:
                raise NotFoundError("Replay has not been started.")
            snapshot = SnapshotRepository(session).get(state.current_snapshot_id)
            if snapshot is None:
                raise NotReadyError("Replay state references a missing snapshot.")
        return SnapshotResponse(snapshot=snapshot, current_snapshot_id=snapshot.snapshot_id)

    def snapshot(self, snapshot_id: UUID) -> SnapshotResponse:
        with self.sessions() as session:
            snapshot = SnapshotRepository(session).get(snapshot_id)
            if snapshot is None:
                raise NotFoundError("Snapshot was not found.", {"snapshot_id": str(snapshot_id)})
            current_id = self._current_id(session)
        return SnapshotResponse(snapshot=snapshot, current_snapshot_id=current_id or snapshot_id)

    def create_decision(
        self,
        snapshot_id: UUID,
        changes: dict[str, float] | None,
        label: str = "Вариант оператора",
    ) -> DecisionResponse:
        snapshot = self._required_snapshot(snapshot_id)
        action = None
        if changes is not None:
            self._validate_signal_ids(changes)
            action = Action(
                action_id=uuid4(),
                label=label,
                origin=ActionOrigin.OPERATOR,
                changes=changes,
            )
        decision = self.runtime.coordinator.decide(snapshot, action, horizon_minutes=60)
        with self.sessions() as session:
            CalculationRepository(session).record(snapshot, decision)
        with self.sessions() as session:
            current_id = self._current_id(session)
        return DecisionResponse(
            decision=decision,
            current_snapshot_id=current_id or snapshot_id,
            stale=current_id is not None and current_id != snapshot_id,
        )

    def evaluate(self, snapshot_id: UUID, changes: dict[str, float]) -> ScenarioResponse:
        self._validate_signal_ids(changes)
        snapshot = self._required_snapshot(snapshot_id)
        action = Action(
            action_id=uuid4(),
            label="Проверка варианта оператора",
            origin=ActionOrigin.OPERATOR,
            changes=changes,
        )
        evaluation = self.runtime.evaluator.evaluate(snapshot, action, 60)
        with self.sessions() as session, session.begin():
            SnapshotRepository(session).put(snapshot)
            EvaluationRepository(session).put(evaluation)
            current_id = self._current_id(session)
        return ScenarioResponse(
            evaluation=evaluation,
            current_snapshot_id=current_id or snapshot_id,
            stale=current_id is not None and current_id != snapshot_id,
        )

    def save_decision(self, decision_id: UUID) -> SaveDecisionResponse:
        with self.sessions() as session:
            try:
                CalculationRepository(session).save(decision_id)
            except KeyError as error:
                raise NotFoundError(
                    "Decision was not found.", {"decision_id": str(decision_id)}
                ) from error
        return SaveDecisionResponse(decision_id=decision_id)

    def decisions(self, *, saved_only: bool, limit: int) -> DecisionListResponse:
        with self.sessions() as session:
            records = DecisionRepository(session).list_records(saved_only=saved_only, limit=limit)
        return DecisionListResponse(
            items=tuple(
                DecisionSummary(
                    decision_id=record.decision.decision_id,
                    snapshot_id=record.decision.snapshot_id,
                    created_at=record.created_at,
                    status=record.decision.status,
                    saved=record.saved_at is not None,
                )
                for record in records
            )
        )

    def decision(self, decision_id: UUID) -> StoredDecisionResponse:
        with self.sessions() as session:
            record = DecisionRepository(session).get_record(decision_id)
            if record is None:
                raise NotFoundError("Decision was not found.", {"decision_id": str(decision_id)})
            current_id = self._current_id(session)
        decision = record.decision
        return StoredDecisionResponse(
            decision=decision,
            current_snapshot_id=current_id or decision.snapshot_id,
            stale=current_id is not None and current_id != decision.snapshot_id,
        )

    def modelled_presets(self) -> ModelledPresetsResponse:
        return ModelledPresetsResponse(items=build_presets())

    def create_modelled_run(self, payload: ModelledChainRequest) -> ModelledRunResponse:
        result = self.modelled_engine.run(payload)
        with self.sessions() as session, session.begin():
            ModelledRunRepository(session).put(result)
        return ModelledRunResponse(result=result)

    def modelled_runs(self, *, limit: int) -> ModelledRunsResponse:
        with self.sessions() as session:
            items = ModelledRunRepository(session).list(limit=limit)
        return ModelledRunsResponse(items=items)

    def modelled_run(self, run_id: UUID) -> ModelledRunResponse:
        with self.sessions() as session:
            result = ModelledRunRepository(session).get(run_id)
        if result is None:
            raise NotFoundError("Modelled run was not found.", {"run_id": str(run_id)})
        return ModelledRunResponse(result=result)

    def _required_snapshot(self, snapshot_id: UUID) -> ProcessSnapshot:
        with self.sessions() as session:
            snapshot = SnapshotRepository(session).get(snapshot_id)
        if snapshot is None:
            raise NotFoundError("Snapshot was not found.", {"snapshot_id": str(snapshot_id)})
        return snapshot

    def _validate_signal_ids(self, changes: dict[str, float]) -> None:
        known = {control.signal_id for control in self.runtime.policy.catalogue.controls}
        unknown = sorted(set(changes) - known)
        if unknown:
            raise RequestError("Unknown control signal IDs.", {"signal_ids": unknown})

    @staticmethod
    def _current_id(session: Session) -> UUID | None:
        state = ReplayRepository(session).get()
        return state.current_snapshot_id if state else None

    def _read_current_id(self) -> UUID | None:
        with self.sessions() as session:
            return self._current_id(session)
