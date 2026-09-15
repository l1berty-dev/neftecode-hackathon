"""Contract-model repositories sharing an explicit caller-owned transaction."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from neftecode_hackathon.contracts import Decision, ProcessSnapshot
from neftecode_hackathon.persistence.models import DecisionRow, EvaluationRow, SnapshotRow


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
        return ProcessSnapshot.model_validate(row.payload) if row else None


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
                or row.decision_id != decision.decision_id
            ):
                raise ValueError("Evaluation ID already belongs to another immutable calculation")

    def get(self, decision_id: UUID) -> Decision | None:
        row = self.session.get(DecisionRow, decision_id)
        return Decision.model_validate(row.payload) if row else None

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
        return tuple(Decision.model_validate(row.payload) for row in rows)
