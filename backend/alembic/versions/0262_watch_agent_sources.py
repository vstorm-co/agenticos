"""Select a real agent for a watch and retain its approved sources on in-flight runs.

Existing watches keep their IDs, findings, clock and active setting. They have no
invented agent assignment: the owner must select one before the next model call.
Run origin/policy are immutable snapshots rather than FKs that deletion could
erase from a parked run's authorization checks.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0262_watch_agent_sources"
down_revision: str | None = "0261_watch_attempt_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name, target, deletion in (
        ("agent_id", "agents", "SET NULL"),
        ("pinned_version_id", "agent_versions", "RESTRICT"),
        ("environment_id", "agent_environments", "SET NULL"),
        ("source_conversation_id", "conversations", "SET NULL"),
    ):
        op.add_column("watches", sa.Column(name, sa.UUID(), nullable=True))
        op.create_foreign_key(
            f"watches_{name}_fkey", "watches", target, [name], ["id"], ondelete=deletion
        )
    op.create_index("watches_agent_id_idx", "watches", ["agent_id"])
    op.add_column("watches", sa.Column("approved_sources", JSONB(), nullable=True))
    op.add_column("watches", sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_watch_version_selection",
        "watches",
        "pinned_version_id IS NULL OR environment_id IS NULL",
    )
    op.create_check_constraint(
        "ck_watch_approved_sources", "watches", "agent_id IS NULL OR approved_sources IS NOT NULL"
    )
    op.drop_constraint("ck_watch_attempt_status", "watches", type_="check")
    op.create_check_constraint(
        "ck_watch_attempt_status",
        "watches",
        "(last_attempt_at IS NULL AND last_attempt_status IS NULL) OR "
        "(last_attempt_at IS NOT NULL AND last_attempt_status IS NOT NULL AND "
        "last_attempt_status IN ('completed', 'source_unavailable', 'access_revoked', 'not_completed', 'needs_agent', 'budget_paused', 'delivery_unavailable'))",
    )
    op.add_column(
        "agent_runs",
        sa.Column("routine_kind", sa.String(16), nullable=False, server_default="trigger"),
    )
    op.add_column("agent_runs", sa.Column("routine_policy", JSONB(), nullable=True))
    op.create_check_constraint(
        "ck_agent_runs_routine_policy",
        "agent_runs",
        "routine_kind IN ('trigger', 'watch') AND "
        "(routine_kind != 'watch' OR (routine_origin_id IS NOT NULL AND routine_policy IS NOT NULL))",
    )


def downgrade() -> None:
    op.drop_constraint("ck_agent_runs_routine_policy", "agent_runs", type_="check")
    op.drop_column("agent_runs", "routine_policy")
    op.drop_column("agent_runs", "routine_kind")
    op.drop_constraint("ck_watch_attempt_status", "watches", type_="check")
    op.execute(
        "UPDATE watches SET last_attempt_at = NULL, last_attempt_status = NULL WHERE last_attempt_status IN ('needs_agent', 'budget_paused', 'delivery_unavailable')"
    )
    op.create_check_constraint(
        "ck_watch_attempt_status",
        "watches",
        "(last_attempt_at IS NULL AND last_attempt_status IS NULL) OR "
        "(last_attempt_at IS NOT NULL AND last_attempt_status IS NOT NULL AND "
        "last_attempt_status IN ('completed', 'source_unavailable', 'access_revoked', 'not_completed'))",
    )
    op.drop_constraint("ck_watch_approved_sources", "watches", type_="check")
    op.drop_constraint("ck_watch_version_selection", "watches", type_="check")
    op.drop_column("watches", "ends_at")
    op.drop_column("watches", "approved_sources")
    op.drop_index("watches_agent_id_idx", "watches")
    for name in ("source_conversation_id", "environment_id", "pinned_version_id", "agent_id"):
        op.drop_constraint(f"watches_{name}_fkey", "watches", type_="foreignkey")
        op.drop_column("watches", name)
