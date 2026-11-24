"""Allow event routines to select fields instead of appending literal context.

Existing routines and queued messages retain their literal meaning. Structured
input belongs to a pending fire or its owner-bound device wait, never to a
settled wait. Do not discard a template configuration or runnable payload on
downgrade: drain it first, then restore the older worker and history contracts.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0364_routine_prompt_templates"
down_revision = "0363_reusable_event_sources"
branch_labels = None
depends_on = None

_ATTEMPT_REASONS = (
    "'platform_identity_required', 'source_review_required', 'agent_unavailable', "
    "'preparation_failed', 'previous_run_active'"
)
_REDACTED_CONTEXT = "status IN ('waiting', 'failed') OR event_context IS NULL"


def upgrade() -> None:
    op.add_column(
        "agent_triggers",
        sa.Column("prompt_mode", sa.String(16), nullable=False, server_default="literal"),
    )
    op.create_check_constraint(
        "ck_trigger_prompt_mode", "agent_triggers", "prompt_mode IN ('literal', 'template')"
    )
    op.create_check_constraint(
        "ck_trigger_template_event",
        "agent_triggers",
        "prompt_mode = 'literal' OR trigger_type = 'event'",
    )
    op.add_column(
        "routine_device_waits", sa.Column("event_body", postgresql.JSONB(), nullable=True)
    )
    op.drop_constraint("ck_routine_device_wait_redacted", "routine_device_waits", type_="check")
    op.create_check_constraint(
        "ck_routine_device_wait_redacted",
        "routine_device_waits",
        f"(status = 'waiting' OR event_body IS NULL) AND ({_REDACTED_CONTEXT})",
    )
    op.add_column("trigger_attempts", sa.Column("error_message", sa.Text(), nullable=True))
    op.drop_constraint("ck_trigger_attempt_reason", "trigger_attempts", type_="check")
    op.create_check_constraint(
        "ck_trigger_attempt_reason",
        "trigger_attempts",
        f"reason IN ({_ATTEMPT_REASONS}, 'prompt_template_failed')",
    )


def downgrade() -> None:
    op.execute(
        "LOCK TABLE agent_triggers, routine_device_waits, trigger_attempts, background_jobs "
        "IN SHARE ROW EXCLUSIVE MODE"
    )
    outstanding = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM agent_triggers WHERE prompt_mode = 'template') "
            "OR EXISTS(SELECT 1 FROM routine_device_waits WHERE event_body IS NOT NULL) "
            "OR EXISTS(SELECT 1 FROM background_jobs WHERE kind = 'fire-trigger' "
            "AND status IN ('queued', 'running', 'dead') AND payload->>'event_body' IS NOT NULL)"
        )
    )
    if outstanding:
        raise RuntimeError(
            "Switch event routines to literal prompts and drain or cancel structured fire jobs "
            "(including retryable dead jobs) and device waits before downgrade"
        )
    # Older workers reject unknown keys even if null. Preserve event_source_id:
    # it identifies the exact shared source authorized at receipt time.
    op.execute(
        "UPDATE background_jobs SET payload = payload - 'event_body' WHERE kind = 'fire-trigger' "
        "AND status IN ('queued', 'running', 'dead') AND payload ? 'event_body'"
    )
    op.execute(
        "UPDATE trigger_attempts SET reason = 'preparation_failed' "
        "WHERE reason = 'prompt_template_failed'"
    )
    op.drop_constraint("ck_trigger_attempt_reason", "trigger_attempts", type_="check")
    op.create_check_constraint(
        "ck_trigger_attempt_reason", "trigger_attempts", f"reason IN ({_ATTEMPT_REASONS})"
    )
    op.drop_column("trigger_attempts", "error_message")
    op.drop_constraint("ck_routine_device_wait_redacted", "routine_device_waits", type_="check")
    op.create_check_constraint(
        "ck_routine_device_wait_redacted", "routine_device_waits", _REDACTED_CONTEXT
    )
    op.drop_column("routine_device_waits", "event_body")
    op.drop_constraint("ck_trigger_template_event", "agent_triggers", type_="check")
    op.drop_constraint("ck_trigger_prompt_mode", "agent_triggers", type_="check")
    op.drop_column("agent_triggers", "prompt_mode")
