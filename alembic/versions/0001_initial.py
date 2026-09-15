"""Initial immutable calculation storage."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    def created() -> sa.Column:
        return sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        )

    op.create_table(
        "snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("dataset_version", sa.String(128), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        created(),
    )
    op.create_index("ix_snapshots_as_of", "snapshots", ["as_of"])
    op.create_table(
        "decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("snapshot_id", sa.Uuid(), sa.ForeignKey("snapshots.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("horizon_minutes", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("constraint_version", sa.String(128), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True)),
        created(),
    )
    op.create_index("ix_decisions_snapshot_id", "decisions", ["snapshot_id"])
    op.create_index("ix_decisions_saved_at", "decisions", ["saved_at"])
    op.create_table(
        "scenario_evaluations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("snapshot_id", sa.Uuid(), sa.ForeignKey("snapshots.id"), nullable=False),
        sa.Column("decision_id", sa.Uuid(), sa.ForeignKey("decisions.id")),
        sa.Column("action", postgresql.JSONB(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        created(),
    )
    op.create_index("ix_scenario_evaluations_snapshot_id", "scenario_evaluations", ["snapshot_id"])
    op.create_index("ix_scenario_evaluations_decision_id", "scenario_evaluations", ["decision_id"])
    op.create_table(
        "replay_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.CheckConstraint("id = 1", name="single_replay_session"),
        sa.Column("episode_id", sa.String(128), nullable=False),
        sa.Column("current_snapshot_id", sa.Uuid(), sa.ForeignKey("snapshots.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("position >= 0", name="replay_position_nonnegative"),
    )


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade is disabled; preserve calculation history")
