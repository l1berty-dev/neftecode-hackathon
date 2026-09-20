"""Opt-in, isolated PostgreSQL 17 tests. Never connect to DATABASE_URL of the user."""

import os
import secrets
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from neftecode_hackathon.contracts import ContractExample
from neftecode_hackathon.persistence.repositories import (
    CalculationRepository,
    DecisionRepository,
    ReplayConflictError,
    ReplayPosition,
    ReplayRepository,
    SnapshotRepository,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_POSTGRES_TESTS") != "1", reason="Opt in to temporary Docker PostgreSQL"
)


@pytest.fixture(scope="module")
def database():
    project = f"neftecode-test-{uuid4().hex[:12]}"
    password = secrets.token_urlsafe(32)
    env = dict(
        os.environ,
        POSTGRES_USER="neftecode",
        POSTGRES_DB="neftecode_test",
        POSTGRES_PASSWORD=password,
        POSTGRES_PORT="0",
    )
    compose = ["docker", "compose", "-p", project, "-f", "compose.yaml"]
    engine = None
    previous = os.environ.get("DATABASE_URL")
    try:
        subprocess.run(
            [*compose, "up", "-d", "--wait", "--wait-timeout", "60"],
            env=env,
            check=True,
            capture_output=True,
        )
        port_result = subprocess.run(
            [*compose, "port", "postgres", "5432"],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        port = int(port_result.stdout.strip().rsplit(":", 1)[1])
        url = URL.create(
            "postgresql+psycopg",
            username="neftecode",
            password=password,
            host="127.0.0.1",
            port=port,
            database="neftecode_test",
        )
        os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
        command.upgrade(Config("alembic.ini"), "head")
        command.check(Config("alembic.ini"))
        engine = create_engine(url)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version()")).startswith("PostgreSQL 17")
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        # Only our randomly named project and newly created test volume are removed.
        subprocess.run([*compose, "down", "--volumes"], env=env, check=True, capture_output=True)


def test_migration_transaction_roundtrip_save_and_reconnect(database):
    example = ContractExample.model_validate_json(
        Path("examples/contract_v1.synthetic.json").read_text()
    )
    with Session(database) as session, session.begin():
        snapshots = SnapshotRepository(session)
        decisions = DecisionRepository(session)
        snapshots.put(example.snapshot)
        snapshots.put(example.snapshot)
        decisions.put(example.decision)
        decisions.put(example.decision)
        first = decisions.save(example.decision.decision_id)
        assert decisions.save(example.decision.decision_id) == first
    database.dispose()
    with Session(database) as session:
        assert SnapshotRepository(session).get(example.snapshot.snapshot_id) == example.snapshot
        assert session.scalar(text("SELECT as_of FROM snapshots")) == example.snapshot.as_of
        assert DecisionRepository(session).get(example.decision.decision_id) == example.decision
        assert DecisionRepository(session).list() == (example.decision,)
        evaluations = (
            example.decision.baseline,
            *((example.decision.preferred,) if example.decision.preferred else ()),
            *example.decision.alternatives,
            *example.decision.rejected_evaluations,
        )
        assert session.scalar(text("SELECT count(*) FROM scenario_evaluations")) == len(
            {evaluation.evaluation_id for evaluation in evaluations}
        )
        with pytest.raises(ValueError), session.begin_nested():
            SnapshotRepository(session).put(
                example.snapshot.model_copy(update={"completeness": 0.5})
            )


def test_fk_and_rollback(database):
    example = ContractExample.model_validate_json(
        Path("examples/contract_v1.synthetic.json").read_text()
    )
    orphan = example.decision.model_copy(update={"decision_id": uuid4(), "snapshot_id": uuid4()})
    with pytest.raises(IntegrityError), Session(database) as session, session.begin():
        DecisionRepository(session).put(orphan)
    with Session(database) as session:
        assert DecisionRepository(session).get(orphan.decision_id) is None
        with pytest.raises(KeyError):
            DecisionRepository(session).save(uuid4())


def _copy_decision_with_new_ids(decision):
    def copied(evaluation):
        return evaluation.model_copy(update={"evaluation_id": uuid4()})

    return decision.model_copy(
        update={
            "decision_id": uuid4(),
            "baseline": copied(decision.baseline),
            "preferred": copied(decision.preferred) if decision.preferred else None,
            "alternatives": tuple(copied(item) for item in decision.alternatives),
            "rejected_evaluations": tuple(copied(item) for item in decision.rejected_evaluations),
        }
    )


def test_atomic_calculation_record_save_and_rollback(database):
    example = ContractExample.model_validate_json(
        Path("examples/contract_v1.synthetic.json").read_text()
    )
    decision = _copy_decision_with_new_ids(example.decision)
    with Session(database) as session:
        CalculationRepository(session).record(example.snapshot, decision)
    with Session(database) as session:
        assert DecisionRepository(session).get(decision.decision_id) == decision

    # A new DecisionRow is inserted first, then an immutable EvaluationRow collision
    # fails. The owned transaction must roll the new decision back.
    conflict = decision.model_copy(update={"decision_id": uuid4()})
    with Session(database) as session:
        with pytest.raises(ValueError, match="Evaluation ID"):
            CalculationRepository(session).record(example.snapshot, conflict)
    with Session(database) as session:
        assert DecisionRepository(session).get(conflict.decision_id) is None

    with Session(database) as session:
        first = CalculationRepository(session).save(decision.decision_id)
    with Session(database) as session:
        assert CalculationRepository(session).save(decision.decision_id) == first
        assert decision in DecisionRepository(session).list()


def test_replay_expected_snapshot_prevents_two_requests_from_skipping(database):
    example = ContractExample.model_validate_json(
        Path("examples/contract_v1.synthetic.json").read_text()
    )
    snapshots = [example.snapshot.model_copy(update={"snapshot_id": uuid4()}) for _ in range(3)]
    with Session(database) as session, session.begin():
        repository = SnapshotRepository(session)
        for snapshot in snapshots:
            repository.put(snapshot)
        replay = ReplayRepository(session)
        assert replay.initialize("episode-a", snapshots[0].snapshot_id) == ReplayPosition(
            "episode-a", snapshots[0].snapshot_id, 0
        )
        assert replay.initialize("episode-a", snapshots[0].snapshot_id) == ReplayPosition(
            "episode-a", snapshots[0].snapshot_id, 0
        )

    first_request = Session(database)
    second_request = Session(database)
    try:
        expected_first = ReplayRepository(first_request).get()
        expected_second = ReplayRepository(second_request).get()
        assert expected_first == expected_second
        advanced = ReplayRepository(second_request).advance(
            "episode-a", expected_second.current_snapshot_id, snapshots[1].snapshot_id
        )
        second_request.commit()
        assert advanced == ReplayPosition("episode-a", snapshots[1].snapshot_id, 1)
        with pytest.raises(ReplayConflictError, match="stale"):
            ReplayRepository(first_request).advance(
                "episode-a", expected_first.current_snapshot_id, snapshots[2].snapshot_id
            )
        first_request.rollback()
    finally:
        first_request.close()
        second_request.close()

    with Session(database) as session, session.begin():
        replay = ReplayRepository(session)
        assert replay.get(for_update=True) == ReplayPosition(
            "episode-a", snapshots[1].snapshot_id, 1
        )
        assert replay.restart(
            "episode-b", snapshots[1].snapshot_id, snapshots[2].snapshot_id
        ) == ReplayPosition("episode-b", snapshots[2].snapshot_id, 0)


def test_replay_conflicts_and_fk_are_explicit(database):
    with Session(database) as session:
        state = ReplayRepository(session).get()
        with pytest.raises(ReplayConflictError):
            ReplayRepository(session).initialize("another", uuid4())
        session.rollback()
        with pytest.raises(ReplayConflictError):
            ReplayRepository(session).advance("wrong-episode", state.current_snapshot_id, uuid4())
        session.rollback()
        with pytest.raises(IntegrityError):
            ReplayRepository(session).advance(state.episode_id, state.current_snapshot_id, uuid4())
        session.rollback()


def test_structured_columns_cannot_silently_disagree_with_payload(database):
    example = ContractExample.model_validate_json(
        Path("examples/contract_v1.synthetic.json").read_text()
    )
    with Session(database) as session:
        with pytest.raises(ValueError, match="structured columns"), session.begin():
            session.execute(
                text("UPDATE decisions SET status = 'corrupt' WHERE id = :id"),
                {"id": example.decision.decision_id},
            )
            DecisionRepository(session).get(example.decision.decision_id)
    with Session(database) as session:
        assert DecisionRepository(session).get(example.decision.decision_id) == example.decision
