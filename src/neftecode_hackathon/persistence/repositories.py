"""Contract repositories plus atomic calculation/replay workflows for PostgreSQL."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from neftecode_hackathon.contracts import Decision, ProcessSnapshot, ScenarioEvaluation
from neftecode_hackathon.persistence.models import (
    DecisionRow,
    EvaluationRow,
    ReplayRow,
    SnapshotRow,
)


class ReplayConflictError(RuntimeError):
    """The caller tried to advance/restart from a stale replay snapshot."""


@dataclass(frozen=True)
class ReplayPosition:
    episode_id: str
    current_snapshot_id: UUID
    position: int


@dataclass(frozen=True)
class DecisionRecord:
    decision: Decision
    created_at: datetime
    saved_at: datetime | None


def _snapshot_from_row(row: SnapshotRow) -> ProcessSnapshot:
    snapshot = ProcessSnapshot.model_validate(row.payload)
    if (
        snapshot.snapshot_id != row.id
        or snapshot.as_of != row.as_of
        or snapshot.mode.value != row.mode
        or snapshot.dataset_version != row.dataset_version
    ):
        raise ValueError("Snapshot structured columns disagree with immutable payload")
    return snapshot


def _decision_from_row(row: DecisionRow) -> Decision:
    decision = Decision.model_validate(row.payload)
    if (
        decision.decision_id != row.id
        or decision.snapshot_id != row.snapshot_id
        or decision.status.value != row.status
        or decision.horizon_minutes != row.horizon_minutes
        or decision.model_version != row.model_version
        or decision.constraint_version != row.constraint_version
    ):
        raise ValueError("Decision structured columns disagree with immutable payload")
    return decision


class SnapshotRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def put(self, snapshot: ProcessSnapshot) -> None:
        payload = snapshot.model_dump(mode="json")
        self.session.execute(
            insert(SnapshotRow)
            .values(
                id=snapshot.snapshot_id,
                as_of=snapshot.as_of,
                mode=snapshot.mode.value,
                dataset_version=snapshot.dataset_version,
                payload=payload,
            )
            .on_conflict_do_nothing(index_elements=[SnapshotRow.id])
        )
        stored = self.get(snapshot.snapshot_id)
        if stored is None or stored.model_dump(mode="json") != payload:
            raise ValueError("Snapshot ID already belongs to a different immutable payload")

    def get(self, snapshot_id: UUID) -> ProcessSnapshot | None:
        row = self.session.get(SnapshotRow, snapshot_id)
        return _snapshot_from_row(row) if row else None


class DecisionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def put(self, decision: Decision) -> None:
        payload = decision.model_dump(mode="json")
        self.session.execute(
            insert(DecisionRow)
            .values(
                id=decision.decision_id,
                snapshot_id=decision.snapshot_id,
                status=decision.status.value,
                horizon_minutes=decision.horizon_minutes,
                model_version=decision.model_version,
                constraint_version=decision.constraint_version,
                payload=payload,
            )
            .on_conflict_do_nothing(index_elements=[DecisionRow.id])
        )
        stored = self.get(decision.decision_id)
        if stored is None or stored.model_dump(mode="json") != payload:
            raise ValueError("Decision ID already belongs to a different immutable payload")
        evaluations = (
            decision.baseline,
            *((decision.preferred,) if decision.preferred else ()),
            *decision.alternatives,
            *decision.rejected_evaluations,
        )
        for evaluation in {e.evaluation_id: e for e in evaluations}.values():
            evaluation_payload = evaluation.model_dump(mode="json")
            self.session.execute(
                insert(EvaluationRow)
                .values(
                    id=evaluation.evaluation_id,
                    snapshot_id=evaluation.snapshot_id,
                    decision_id=decision.decision_id,
                    action=evaluation.action.model_dump(mode="json"),
                    payload=evaluation_payload,
                )
                .on_conflict_do_nothing(index_elements=[EvaluationRow.id])
            )
            row = self.session.get(EvaluationRow, evaluation.evaluation_id)
            if (
                row is None
                or row.payload != evaluation_payload
                or row.snapshot_id != evaluation.snapshot_id
                or row.decision_id != decision.decision_id
                or row.action != evaluation.action.model_dump(mode="json")
            ):
                raise ValueError("Evaluation ID already belongs to another immutable calculation")

    def get(self, decision_id: UUID) -> Decision | None:
        row = self.session.get(DecisionRow, decision_id)
        return _decision_from_row(row) if row else None

    def save(self, decision_id: UUID) -> datetime:
        saved_at = self.session.scalar(
            update(DecisionRow)
            .where(
                DecisionRow.id == decision_id,
            )
            .values(saved_at=func.coalesce(DecisionRow.saved_at, func.now()))
            .returning(DecisionRow.saved_at)
        )
        if saved_at is None:
            raise KeyError(decision_id)
        return saved_at

    def list(self, *, saved_only: bool = True, limit: int = 20) -> tuple[Decision, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        query = select(DecisionRow)
        if saved_only:
            query = query.where(DecisionRow.saved_at.is_not(None))
        rows = self.session.scalars(
            query.order_by(
                DecisionRow.created_at.desc(),
                DecisionRow.id,
            ).limit(limit)
        )
        return tuple(_decision_from_row(row) for row in rows)

    def get_record(self, decision_id: UUID) -> DecisionRecord | None:
        row = self.session.get(DecisionRow, decision_id)
        if row is None:
            return None
        return DecisionRecord(_decision_from_row(row), row.created_at, row.saved_at)

    def list_records(
        self, *, saved_only: bool = True, limit: int = 20
    ) -> tuple[DecisionRecord, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        query = select(DecisionRow)
        if saved_only:
            query = query.where(DecisionRow.saved_at.is_not(None))
        rows = self.session.scalars(
            query.order_by(DecisionRow.created_at.desc(), DecisionRow.id).limit(limit)
        )
        return tuple(
            DecisionRecord(_decision_from_row(row), row.created_at, row.saved_at) for row in rows
        )


class EvaluationRepository:
    """Persist one standalone scenario evaluation inside a caller-owned transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def put(self, evaluation: ScenarioEvaluation) -> None:
        payload = evaluation.model_dump(mode="json")
        action = evaluation.action.model_dump(mode="json")
        self.session.execute(
            insert(EvaluationRow)
            .values(
                id=evaluation.evaluation_id,
                snapshot_id=evaluation.snapshot_id,
                decision_id=None,
                action=action,
                payload=payload,
            )
            .on_conflict_do_nothing(index_elements=[EvaluationRow.id])
        )
        row = self.session.get(EvaluationRow, evaluation.evaluation_id)
        if (
            row is None
            or row.payload != payload
            or row.snapshot_id != evaluation.snapshot_id
            or row.decision_id is not None
            or row.action != action
        ):
            raise ValueError("Evaluation ID already belongs to another immutable calculation")


class CalculationRepository:
    """Persist one snapshot, decision and all evaluations in one owned transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def record(self, snapshot: ProcessSnapshot, decision: Decision) -> None:
        snapshot = ProcessSnapshot.model_validate(snapshot.model_dump())
        decision = Decision.model_validate(decision.model_dump())
        if decision.snapshot_id != snapshot.snapshot_id:
            raise ValueError("Decision and snapshot IDs do not match")
        if self.session.in_transaction():
            raise RuntimeError("CalculationRepository.record requires a fresh Session")
        with self.session.begin():
            SnapshotRepository(self.session).put(snapshot)
            DecisionRepository(self.session).put(decision)
            self.session.flush()

    def save(self, decision_id: UUID) -> datetime:
        if self.session.in_transaction():
            raise RuntimeError("CalculationRepository.save requires a fresh Session")
        with self.session.begin():
            saved_at = DecisionRepository(self.session).save(decision_id)
            self.session.flush()
            return saved_at


class ReplayRepository:
    """Single local replay cursor; caller owns the surrounding transaction."""

    _ROW_ID = 1

    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _validate_episode(episode_id: str) -> None:
        if not episode_id or len(episode_id) > 128:
            raise ValueError("episode_id must contain 1..128 characters")

    @staticmethod
    def _position(row: ReplayRow) -> ReplayPosition:
        return ReplayPosition(row.episode_id, row.current_snapshot_id, row.position)

    def get(self, *, for_update: bool = False) -> ReplayPosition | None:
        query = select(ReplayRow).where(ReplayRow.id == self._ROW_ID)
        if for_update:
            query = query.with_for_update()
        row = self.session.scalar(query.execution_options(populate_existing=True))
        return self._position(row) if row else None

    def initialize(
        self, episode_id: str, current_snapshot_id: UUID, *, position: int = 0
    ) -> ReplayPosition:
        self._validate_episode(episode_id)
        if position < 0:
            raise ValueError("position must be nonnegative")
        self.session.execute(
            insert(ReplayRow)
            .values(
                id=self._ROW_ID,
                episode_id=episode_id,
                current_snapshot_id=current_snapshot_id,
                position=position,
            )
            .on_conflict_do_nothing(index_elements=[ReplayRow.id])
        )
        state = self.get(for_update=True)
        expected = ReplayPosition(episode_id, current_snapshot_id, position)
        if state != expected:
            raise ReplayConflictError(f"Replay already initialized at {state}")
        return state

    def advance(
        self, episode_id: str, expected_snapshot_id: UUID, next_snapshot_id: UUID
    ) -> ReplayPosition:
        self._validate_episode(episode_id)
        row = self.session.execute(
            update(ReplayRow)
            .where(
                ReplayRow.id == self._ROW_ID,
                ReplayRow.episode_id == episode_id,
                ReplayRow.current_snapshot_id == expected_snapshot_id,
            )
            .values(
                current_snapshot_id=next_snapshot_id,
                position=ReplayRow.position + 1,
            )
            .returning(
                ReplayRow.episode_id,
                ReplayRow.current_snapshot_id,
                ReplayRow.position,
            )
        ).one_or_none()
        if row is None:
            raise ReplayConflictError("Replay changed; expected_snapshot_id is stale")
        return ReplayPosition(*row)

    def restart(
        self, episode_id: str, expected_snapshot_id: UUID, first_snapshot_id: UUID
    ) -> ReplayPosition:
        self._validate_episode(episode_id)
        row = self.session.execute(
            update(ReplayRow)
            .where(
                ReplayRow.id == self._ROW_ID,
                ReplayRow.current_snapshot_id == expected_snapshot_id,
            )
            .values(
                episode_id=episode_id,
                current_snapshot_id=first_snapshot_id,
                position=0,
            )
            .returning(
                ReplayRow.episode_id,
                ReplayRow.current_snapshot_id,
                ReplayRow.position,
            )
        ).one_or_none()
        if row is None:
            raise ReplayConflictError("Replay changed; expected_snapshot_id is stale")
        return ReplayPosition(*row)
