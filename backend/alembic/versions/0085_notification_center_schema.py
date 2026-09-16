"""Notification center schema: the four new tables, and who to notify (#1598).

Schema-only, the first phase of `docs/design/notification-center-plan.md`: no
route, service or worker in this repository writes to any of these tables yet.

`notifications` is the durable, per-recipient row (Decision 2) - one per event
per person it is addressed to, deduplicated by
`(recipient_user_id, event_type, occurrence_id)`. `notification_deliveries` is
the claimed, retried side-channel send off it (Decision 3).
`notification_preferences` is the per-user, per-event, per-channel toggle
(Decision 4) - deliberately not named `notification_preference` after the
model class, since `app.db.models.user.NotificationPreference` already names
the `Literal` for the three legacy boolean columns this table does not
replace. `announcements` is the app-admin composer's own row (Decision 5).

`rag_documents.initiated_by_user_id`/`ingestion_attempt` and
`sync_logs.triggered_by_user_id` are who an ingestion event's audience
resolves to, and the dispatch-time attempt counter its occurrence id needs to
survive a retry without colliding with the attempt before it - nothing in the
ingestion pipeline persisted either before this (Decision 1).

Revision ID: 0085_notification_center_schema
Revises: 0085_refresh_reuse
Create Date: 2026-09-15

Renumbered from 0080 - `main` gained its own, unrelated `0080`-`0084` range
(#1420's own per-organization retention policies among them) while this stack
sat stacked and unmerged, so the original number collided with a real file on
`main` rather than only with an in-memory revision id. `main` kept moving
after that first reconciliation too - `0085_refresh_reuse` (#1719) landed
chained onto the same `0084_retention_policies` this file was, so this is its
second re-chaining, not its first, and is unlikely to be its last before this
stack actually merges: whoever next resolves a "multiple heads" failure here
should re-merge `main` and point `down_revision` at whatever `main`'s head
is by then, not assume this file already names it.

Chained onto `main`'s current head with `main` actually merged into this
stack - both migration chains and the *models* `main`'s own migrations pair
with are present together, so `alembic check` sees `main`'s tables and
columns as declared rather than removed. Chaining onto a revision from a
different history without its models was tried first and reverted for
exactly that reason.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0085_notification_center_schema"
down_revision: str | None = "0085_refresh_reuse"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_TYPE_VALUES = (
    "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
    "'ingestion_completed', 'ingestion_failed', 'usage_report', "
    "'agent_usage_report', 'security_event', 'configuration_changed', 'announcement'"
)


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        # No FK, deliberately - see app/db/models/announcement.py: this is
        # audit-adjacent evidence, the same choice app_admin_audit_logs already
        # makes for actor_user_id, and must not become undeletable-by-cascade
        # the moment the sender's own account is later removed.
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("audience_spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("audience_description", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="announcements_pkey"),
    )
    op.create_index("announcements_actor_user_id_idx", "announcements", ["actor_user_id"])

    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recipient_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("occurrence_id", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("context_url", sa.Text(), nullable=True),
        sa.Column("render_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("in_app_visible", sa.Boolean(), nullable=False),
        sa.Column("announcement_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"event_type IN ({_EVENT_TYPE_VALUES})", name="ck_notifications_event_type"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="notifications_organization_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"],
            ["users.id"],
            name="notifications_recipient_user_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["announcement_id"],
            ["announcements.id"],
            name="notifications_announcement_id_fkey",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="notifications_pkey"),
    )
    op.create_index("notifications_organization_id_idx", "notifications", ["organization_id"])
    op.create_index("notifications_announcement_id_idx", "notifications", ["announcement_id"])
    op.create_index(
        "notifications_recipient_event_occurrence_idx",
        "notifications",
        ["recipient_user_id", "event_type", "occurrence_id"],
        unique=True,
    )
    # The paginated inbox: `id` breaks a tie `created_at` alone cannot, since one
    # transaction (a report flow writing several recipients' rows together) can
    # give more than one row the identical timestamp. `text(...)` for the
    # descending columns - a plain string would be quoted as one identifier
    # named "created_at DESC".
    op.create_index(
        "notifications_inbox_idx",
        "notifications",
        ["recipient_user_id", sa.text("created_at DESC"), sa.text("id DESC")],
        postgresql_where=sa.text("in_app_visible"),
    )
    # The unread-count badge.
    op.create_index(
        "notifications_unread_idx",
        "notifications",
        ["recipient_user_id"],
        postgresql_where=sa.text("in_app_visible AND read_at IS NULL"),
    )

    op.create_table(
        "notification_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notification_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("channel = 'email'", name="ck_notification_deliveries_channel"),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'skipped')",
            name="ck_notification_deliveries_status",
        ),
        sa.ForeignKeyConstraint(
            ["notification_id"],
            ["notifications.id"],
            name="notification_deliveries_notification_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="notification_deliveries_pkey"),
    )
    op.create_index(
        "notification_deliveries_notification_id_idx",
        "notification_deliveries",
        ["notification_id"],
    )
    op.create_index(
        "notification_deliveries_claim_idx",
        "notification_deliveries",
        ["status", "claimed_until"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "notification_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"event_type IN ({_EVENT_TYPE_VALUES})", name="ck_notification_preferences_event_type"
        ),
        sa.CheckConstraint(
            "channel IN ('in_app', 'email')", name="ck_notification_preferences_channel"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="notification_preferences_user_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="notification_preferences_pkey"),
        sa.UniqueConstraint(
            "user_id",
            "event_type",
            "channel",
            name="uq_notification_preferences_user_event_channel",
        ),
    )
    op.create_index("notification_preferences_user_id_idx", "notification_preferences", ["user_id"])

    op.add_column(
        "rag_documents",
        sa.Column("initiated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "rag_documents",
        sa.Column("ingestion_attempt", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_index(
        "rag_documents_initiated_by_user_id_idx", "rag_documents", ["initiated_by_user_id"]
    )
    op.create_foreign_key(
        "rag_documents_initiated_by_user_id_fkey",
        "rag_documents",
        "users",
        ["initiated_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "sync_logs", sa.Column("triggered_by_user_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_index("sync_logs_triggered_by_user_id_idx", "sync_logs", ["triggered_by_user_id"])
    op.create_foreign_key(
        "sync_logs_triggered_by_user_id_fkey",
        "sync_logs",
        "users",
        ["triggered_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("sync_logs_triggered_by_user_id_fkey", "sync_logs", type_="foreignkey")
    op.drop_index("sync_logs_triggered_by_user_id_idx", table_name="sync_logs")
    op.drop_column("sync_logs", "triggered_by_user_id")

    op.drop_constraint(
        "rag_documents_initiated_by_user_id_fkey", "rag_documents", type_="foreignkey"
    )
    op.drop_index("rag_documents_initiated_by_user_id_idx", table_name="rag_documents")
    op.drop_column("rag_documents", "ingestion_attempt")
    op.drop_column("rag_documents", "initiated_by_user_id")

    op.drop_table("notification_preferences")

    op.drop_index("notification_deliveries_claim_idx", table_name="notification_deliveries")
    op.drop_index(
        "notification_deliveries_notification_id_idx", table_name="notification_deliveries"
    )
    op.drop_table("notification_deliveries")

    op.drop_index("notifications_unread_idx", table_name="notifications")
    op.drop_index("notifications_inbox_idx", table_name="notifications")
    op.drop_index("notifications_recipient_event_occurrence_idx", table_name="notifications")
    op.drop_index("notifications_announcement_id_idx", table_name="notifications")
    op.drop_index("notifications_organization_id_idx", table_name="notifications")
    op.drop_table("notifications")

    op.drop_index("announcements_actor_user_id_idx", table_name="announcements")
    op.drop_table("announcements")
