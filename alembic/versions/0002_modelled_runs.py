"""Store modelled full-chain calculations separately from historical decisions."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "modelled_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("preset_id", sa.String(128)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("constraint_version", sa.String(128), nullable=False),
        sa.Column("request_payload", postgresql.JSONB(), nullable=False),
        sa.Column("result_payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_modelled_runs_preset_id", "modelled_runs", ["preset_id"])
    op.create_index("ix_modelled_runs_status", "modelled_runs", ["status"])
    op.create_index("ix_modelled_runs_created_at", "modelled_runs", ["created_at"])


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade is disabled; preserve modelled run history")
