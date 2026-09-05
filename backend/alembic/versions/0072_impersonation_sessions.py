"""An impersonation is a session row, so it can be ended (#1044).

`POST /admin/users/{id}/impersonate` used to mint a bare one-hour access token
and hand it back. Nothing recorded that it existed, so nothing could revoke it:
the target changing their password, the administrator closing the tab, an
operator wanting it gone - the token was good for its full hour whatever anybody
did. It was the one credential on the platform that outlived every control the
platform has (#943).

`sessions.impersonator_user_id` makes an impersonation a row in the table that
already holds every other credential: null on an ordinary sign-in, the
administrator's id on an impersonation. The access token names its row in a
`sid` claim and the auth dependency refuses a token whose row is gone, ended or
expired - so `DELETE /sessions`, a password reset and the administrator's own
"End impersonation" all stop it at once, through the machinery that already
existed. `ON DELETE CASCADE`, because a deleted administrator's impersonation
should end with them. The partial index is what that cascade walks; a plain
index would carry every ordinary session for a column that is null on all of
them.

`deployment_settings.notify_impersonated_users` is the policy question the
issue asked to be decided rather than defaulted: whether the person is emailed
when an administrator acts as them. Off by default, because a self-hosted
deployment is a company's own installation and the operator decides; a
deployment that turns it on gets an email per impersonation.

Nothing is backfilled. Every row already in `sessions` is somebody's own
sign-in, and a token minted before this revision carries no `sid`, so it is
refused from the first request after the upgrade - which is the point.

Revision ID: 0072_impersonation_sessions
Revises: 0071_mcp_connection_catalog_key
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0072_impersonation_sessions"
down_revision: str | None = "0071_mcp_connection_catalog_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("impersonator_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "sessions_impersonator_user_id_fkey",
        "sessions",
        "users",
        ["impersonator_user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "sessions_impersonator_user_id_idx",
        "sessions",
        ["impersonator_user_id"],
        postgresql_where=sa.text("impersonator_user_id IS NOT NULL"),
    )
    op.add_column(
        "deployment_settings",
        sa.Column(
            "notify_impersonated_users",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("deployment_settings", "notify_impersonated_users")
    op.drop_index("sessions_impersonator_user_id_idx", table_name="sessions")
    op.drop_constraint("sessions_impersonator_user_id_fkey", "sessions", type_="foreignkey")
    op.drop_column("sessions", "impersonator_user_id")
