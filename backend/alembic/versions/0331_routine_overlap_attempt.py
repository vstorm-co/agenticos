"""Keep a history entry when a routine skips an overlapping occurrence.

Downgrade removes only these new, unbilled history entries before restoring
the old reason constraint; agent runs and their spend are unchanged.
"""

from alembic import op

revision: str = "0331_routine_overlap_attempt"
down_revision: str = "0330_linear_trigger"
branch_labels: None = None
depends_on: None = None

_OLD = "'platform_identity_required', 'source_review_required', 'agent_unavailable', 'preparation_failed'"


def _set_reasons(reasons: str) -> None:
    op.drop_constraint("ck_trigger_attempt_reason", "trigger_attempts", type_="check")
    op.create_check_constraint(
        "ck_trigger_attempt_reason", "trigger_attempts", f"reason IN ({reasons})"
    )


def upgrade() -> None:
    _set_reasons(_OLD + ", 'previous_run_active'")


def downgrade() -> None:
    op.execute("DELETE FROM trigger_attempts WHERE reason = 'previous_run_active'")
    _set_reasons(_OLD)
