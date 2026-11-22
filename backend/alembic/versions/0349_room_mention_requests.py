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
# The names the naming convention gave these two checks. Raw SQL needs them
# spelled out; `op.create_check_constraint` would derive them from the short form.
_EVENT_CHECKS = (
    (
        "notifications",
        "ck_notifications_event_type",
        "notifications_ck_notifications_event_type_check",
    ),
    (
        "notification_preferences",
        "ck_notification_preferences_event_type",
        "notification_preferences_ck_notification_preferences_ev_cd4d",
    ),
)


_VALIDATIONS = (
    ("notifications", _EVENT_CHECKS[0][2]),
    ("notification_preferences", _EVENT_CHECKS[1][2]),
    ("room_submissions", "fk_room_submission_parent"),
    ("room_submissions", "room_submissions_child_request_check"),
    ("room_submissions", "room_submissions_dispatch_check"),
)
_INDEXES = (
    (
        "uq_room_submission_client",
        ["organization_id", "conversation_id", "requester_id", "client_message_id"],
        "parent_submission_id IS NULL",
    ),
    ("uq_room_submission_message", ["message_id"], "parent_submission_id IS NULL"),
    (
        "uq_room_submission_post_agent",
        [sa.text("COALESCE(parent_submission_id, id)"), "agent_id"],
        "agent_id IS NOT NULL",
    ),
)
_LEGACY_CLIENT = "uq_room_submission_client_legacy"


def _event_checks(values: str) -> None:
    for table, name, _full in _EVENT_CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"event_type IN ({values})")


def _add_not_valid(table: str, name: str, definition: str) -> None:
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} {definition} NOT VALID")


def _event_checks_not_valid(values: str) -> None:
    for table, _short, full in _EVENT_CHECKS:
        _add_not_valid(table, full, f"CHECK (event_type IN ({values}))")


def _drop_unbuilt_index(name: str) -> None:
    # A concurrent unique build that failed leaves an INVALID index of the same
    # name. IF NOT EXISTS would skip it and the uniqueness would never apply.
    invalid = op.get_bind().scalar(
        sa.text(
            "SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            "WHERE c.relname = :name AND c.relnamespace = current_schema()::regnamespace "
            "AND NOT i.indisvalid"
        ),
        {"name": name},
    )
    if invalid:
        op.drop_index(name, table_name="room_submissions", postgresql_concurrently=True)


def upgrade() -> None:
    # `messages` and `room_submissions` already hold rows. Every ALTER below is
    # catalog-only: nullable or constant-default columns do not rewrite the
    # table, and each constraint is added NOT VALID. The partial unique indexes
    # build CONCURRENTLY outside the DDL transaction, so no lock outlives a
    # statement, and the old full unique constraints go only after their
    # replacements exist, so duplicate protection never lapses. The scans that
    # prove existing rows run last, taking only SHARE UPDATE EXCLUSIVE.
    # Every step tolerates a retry after an interrupted run.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "messages",
        sa.Column(
            "room_mentions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        if_not_exists=True,
    )
    op.add_column(
        "room_submissions",
        sa.Column("parent_submission_id", sa.UUID(), nullable=True),
        if_not_exists=True,
    )
    op.add_column(
        "room_submissions",
        sa.Column("dispatch", sa.String(16), nullable=False, server_default="explicit"),
        if_not_exists=True,
    )
    # The new partial index reuses this constraint's name; step it aside.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_constraint WHERE contype = 'u' "
        "AND conrelid = 'room_submissions'::regclass "
        "AND conname = 'uq_room_submission_client') THEN "
        "ALTER TABLE room_submissions RENAME CONSTRAINT uq_room_submission_client "
        f"TO {_LEGACY_CLIENT}; END IF; END $$"
    )
    with op.get_context().autocommit_block():
        for name, columns, predicate in _INDEXES:
            _drop_unbuilt_index(name)
            op.create_index(
                name,
                "room_submissions",
                columns,
                unique=True,
                postgresql_where=sa.text(predicate),
                postgresql_concurrently=True,
                if_not_exists=True,
            )
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(f"ALTER TABLE room_submissions DROP CONSTRAINT IF EXISTS {_LEGACY_CLIENT}")
    op.execute(
        "ALTER TABLE room_submissions DROP CONSTRAINT IF EXISTS room_submissions_message_id_key"
    )
    _add_not_valid(
        "room_submissions",
        "fk_room_submission_parent",
        "FOREIGN KEY (organization_id, conversation_id, parent_submission_id) "
        "REFERENCES room_submissions (organization_id, conversation_id, id) "
        "ON DELETE CASCADE",
    )
    _add_not_valid(
        "room_submissions",
        "room_submissions_child_request_check",
        "CHECK (parent_submission_id IS NULL OR "
        "(parent_submission_id <> id AND intent = 'message' AND agent_id IS NOT NULL))",
    )
    _add_not_valid(
        "room_submissions",
        "room_submissions_dispatch_check",
        "CHECK (dispatch IN ('explicit', 'mention', 'automatic'))",
    )
    _event_checks_not_valid(f"{_EVENTS_BEFORE}, 'room_mention', 'room_thread_reply'")
    with op.get_context().autocommit_block():
        for table, name in _VALIDATIONS:
            op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


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
    op.drop_index("uq_room_submission_post_agent", table_name="room_submissions", if_exists=True)
    op.drop_index("uq_room_submission_message", table_name="room_submissions", if_exists=True)
    op.drop_index("uq_room_submission_client", table_name="room_submissions", if_exists=True)
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
