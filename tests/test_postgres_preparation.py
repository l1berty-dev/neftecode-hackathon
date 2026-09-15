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
from neftecode_hackathon.persistence.repositories import DecisionRepository, SnapshotRepository

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
