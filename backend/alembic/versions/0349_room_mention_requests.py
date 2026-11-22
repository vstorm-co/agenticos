"""Keep one human post while queueing each mentioned bot independently.

Existing room submissions remain roots with their original ids, fingerprints,
run links and queue order. Extra replies share that root and message. A rollback
refuses to discard new mention, fan-out or notification evidence.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0349_room_mention_requests"
down_revision: str = "0348_room_participants"
branch_labels: None = None
depends_on: None = None

_EVENTS_BEFORE = (
    "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
    "'ingestion_completed', 'ingestion_failed', 'usage_report', "
    "'agent_usage_report', 'security_event', 'configuration_changed', "
    "'announcement', 'artifact_version_published', 'resource_shared', "
    "'budget_warning', 'mcp_server_down', 'mcp_server_recovered', "
    "'background_task_paused', 'eval_suite_failed', 'promotion_overridden', "
    "'shared_change_applied', 'workflow_notification', "
    "'artifact_owner_changed', 'artifact_share_requested', "
    "'capability_requested', 'suggestion', 'finding', 'improvement_finished', "
    "'eval_suite_reevaluated', 'eval_run_finished', 'case_generation_finished', "
    "'workflow_log_alert'"
)
_EVENT_CHECKS = (
    ("notifications", "ck_notifications_event_type"),
    ("notification_preferences", "ck_notification_preferences_event_type"),
)


def _event_checks(values: str) -> None:
    for table, name in _EVENT_CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"event_type IN ({values})")


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "room_mentions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("room_submissions", sa.Column("parent_submission_id", sa.UUID(), nullable=True))
    op.add_column(
        "room_submissions",
        sa.Column("dispatch", sa.String(16), nullable=False, server_default="explicit"),
    )
    op.drop_constraint("uq_room_submission_client", "room_submissions", type_="unique")
    op.drop_constraint("room_submissions_message_id_key", "room_submissions", type_="unique")
    op.create_index(
        "uq_room_submission_client",
        "room_submissions",
        ["organization_id", "conversation_id", "requester_id", "client_message_id"],
        unique=True,
        postgresql_where=sa.text("parent_submission_id IS NULL"),
    )
    op.create_index(
        "uq_room_submission_message",
        "room_submissions",
        ["message_id"],
        unique=True,
        postgresql_where=sa.text("parent_submission_id IS NULL"),
    )
    op.create_index(
        "uq_room_submission_post_agent",
        "room_submissions",
        [sa.text("COALESCE(parent_submission_id, id)"), "agent_id"],
        unique=True,
        postgresql_where=sa.text("agent_id IS NOT NULL"),
    )
    op.create_foreign_key(
        "fk_room_submission_parent",
        "room_submissions",
        "room_submissions",
        ["organization_id", "conversation_id", "parent_submission_id"],
        ["organization_id", "conversation_id", "id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "child_request",
        "room_submissions",
        "parent_submission_id IS NULL OR "
        "(parent_submission_id <> id AND intent = 'message' AND agent_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "dispatch", "room_submissions", "dispatch IN ('explicit', 'mention', 'automatic')"
    )
    _event_checks(f"{_EVENTS_BEFORE}, 'room_mention', 'room_thread_reply'")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        "LOCK TABLE room_submissions, messages, notifications, notification_preferences "
        "IN ACCESS EXCLUSIVE MODE"
    )
    used = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM room_submissions WHERE "
            "parent_submission_id IS NOT NULL OR dispatch <> 'explicit') OR "
            "EXISTS (SELECT 1 FROM messages WHERE room_mentions <> '[]'::jsonb) OR "
            "EXISTS (SELECT 1 FROM notifications WHERE "
            "event_type IN ('room_mention', 'room_thread_reply')) OR "
            "EXISTS (SELECT 1 FROM notification_preferences WHERE "
            "event_type IN ('room_mention', 'room_thread_reply'))"
        )
    )
    if used:
        raise RuntimeError(
            "Cannot discard room mentions, extra agent requests or notification evidence"
        )
    _event_checks(_EVENTS_BEFORE)
    op.drop_constraint("dispatch", "room_submissions", type_="check")
    op.drop_constraint("child_request", "room_submissions", type_="check")
    op.drop_constraint("fk_room_submission_parent", "room_submissions", type_="foreignkey")
    op.drop_index("uq_room_submission_post_agent", table_name="room_submissions")
    op.drop_index("uq_room_submission_message", table_name="room_submissions")
    op.drop_index("uq_room_submission_client", table_name="room_submissions")
    op.create_unique_constraint(
        "uq_room_submission_client",
        "room_submissions",
        ["organization_id", "conversation_id", "requester_id", "client_message_id"],
    )
    op.create_unique_constraint(
        "room_submissions_message_id_key", "room_submissions", ["message_id"]
    )
    op.drop_column("room_submissions", "dispatch")
    op.drop_column("room_submissions", "parent_submission_id")
    op.drop_column("messages", "room_mentions")
