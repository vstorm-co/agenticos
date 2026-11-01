"""Requests to share a page, or to confirm one of its versions (#1974).

A page that reads live data reaches only its owner and the roles that open every page
until its owner shares it. Somebody who may not decide that - an editor widening who
opens it, a member who cannot open it, an editor whose republish changed what it reads -
asks, and `artifact_share_requests` is where the asking is kept: one table, three
`kind`s (`audience`, `access`, `version`), and a `status` that ends in `approved`,
`declined` or `voided` (a page query that changed, a new owner, an archived page, a
newer request replacing it; `void_reason` says which).

Two partial unique indexes hold the rule that a newer request replaces an older one:
one pending `audience` or `access` request per page, person and kind, and one pending
`version` request per page whoever made it. The service voids the older row, under the
page's lock, before it inserts the new one; the indexes are what a race loses to.

`requester_membership_id` is a plain id, not a key, as the consent columns are:
re-inviting a member makes a new membership, and what they asked before must not stand
for the new one. `version_id` is deleted with its version.

The new notification type, `artifact_share_requested`, goes into the CHECKs on
`notifications.event_type` and `notification_preferences.event_type` as
`0216_artifact_owner_changed` did for its type; the downgrade deletes rows of the new type
before restoring the narrower CHECKs.

Revision ID: 0217_artifact_share_requests
Revises: 0216_artifact_owner_changed
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0217_artifact_share_requests"
down_revision: str | Sequence[str] | None = "0216_artifact_owner_changed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = (
    "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
    "'ingestion_completed', 'ingestion_failed', 'usage_report', "
    "'agent_usage_report', 'security_event', 'configuration_changed', 'announcement', "
    "'artifact_version_published', 'resource_shared', 'budget_warning', "
    "'mcp_server_down', 'mcp_server_recovered', 'background_task_paused', 'capability_requested', 'suggestion', 'finding', "
    "'workflow_notification', 'artifact_owner_changed'"
)
_AFTER = f"{_BEFORE}, 'artifact_share_requested'"

_CHECKS = (
    ("notifications", "ck_notifications_event_type"),
    ("notification_preferences", "ck_notification_preferences_event_type"),
)

_TABLE = "artifact_share_requests"


def _recreate(values: str) -> None:
    for table, name in _CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"event_type IN ({values})")


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        _TABLE,
        sa.Column("id", uuid, nullable=False),
        sa.Column("organization_id", uuid, nullable=False),
        sa.Column("artifact_id", uuid, nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("requester_user_id", uuid, nullable=False),
        sa.Column("requester_membership_id", uuid, nullable=True),
        sa.Column("version_id", uuid, nullable=True),
        sa.Column("query_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("requested_visibility", sa.String(length=16), nullable=True),
        sa.Column("requested_subjects", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("void_reason", sa.String(length=32), nullable=True),
        sa.Column("decided_by_user_id", uuid, nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('audience', 'access', 'version')",
            name=op.f("artifact_share_requests_ck_share_request_kind_check"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'declined', 'voided')",
            name=op.f("artifact_share_requests_ck_share_request_status_check"),
        ),
        sa.CheckConstraint(
            "requested_visibility IS NULL OR requested_visibility IN ('team', 'org')",
            name=op.f("artifact_share_requests_ck_share_request_visibility_check"),
        ),
        sa.CheckConstraint(
            "note IS NULL OR char_length(note) <= 500",
            name=op.f("artifact_share_requests_ck_share_request_note_check"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("artifact_share_requests_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifacts.id"],
            name=op.f("artifact_share_requests_artifact_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requester_user_id"],
            ["users.id"],
            name=op.f("artifact_share_requests_requester_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["artifact_versions.id"],
            name=op.f("artifact_share_requests_version_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            name=op.f("artifact_share_requests_decided_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("artifact_share_requests_pkey")),
    )
    op.create_index(
        op.f("artifact_share_requests_organization_id_idx"), _TABLE, ["organization_id"]
    )
    op.create_index(op.f("artifact_share_requests_artifact_id_idx"), _TABLE, ["artifact_id"])
    op.create_index(
        "uq_artifact_share_request_pending",
        _TABLE,
        ["artifact_id", "requester_user_id", "kind"],
        unique=True,
        postgresql_where=sa.text("status = 'pending' AND kind <> 'version'"),
    )
    op.create_index(
        "uq_artifact_share_request_pending_version",
        _TABLE,
        ["artifact_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending' AND kind = 'version'"),
    )
    _recreate(_AFTER)


def downgrade() -> None:
    for table, _name in _CHECKS:
        op.execute(f"DELETE FROM {table} WHERE event_type = 'artifact_share_requested'")
    _recreate(_BEFORE)
    op.drop_table(_TABLE)
