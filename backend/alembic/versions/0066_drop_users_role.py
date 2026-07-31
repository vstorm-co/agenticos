"""Drop users.role, the last of the template's role column

Revision ID: 0066_drop_users_role
Revises: 0065_env_observability
Create Date: 2026-07-31

`users.role` (`admin` | `user`) came from the project template and was never
this platform's authorization model. Authority inside an organization is a
membership row plus the permission catalog in `app/core/permissions.py`;
administering the *deployment* is the `is_app_admin` flag. The column was a
third answer to a question that already had two, and it agreed with neither.

Mostly it decided nothing, which is the worse half of the problem: an account
called `admin@example.com` sitting at `role = 'user'` reads as a broken
installation, and the first thing anybody does is try to fix the wrong layer.

It was not entirely inert, and that is why this is a behaviour change rather
than a tidy-up. `GET /conversations/{id}` and its `/messages` sibling passed
`user_id=None` - "do not filter by owner" - for anybody whose `role` said
`admin`, so one person's conversation with an agent was readable by another on
the strength of a column nothing else on the platform respected. Cross-user
conversation reads are a deployment-administration act and already live on
`/admin/conversations`, gated on `is_app_admin`. Those two routes are now
always scoped to the caller.

Nothing is backfilled onto `is_app_admin`. The two are not synonyms - one
governed a template's idea of an admin, the other reaches every organization on
the deployment - and inferring the second from the first would silently hand
somebody the whole estate. Any account that genuinely needs it is granted
explicitly:

    agenticos cmd create-app-admin someone@example.com

Downgrade restores the column at its old default, which is all it can honestly
do: the values are not recoverable, and re-deriving them from `is_app_admin`
would invent history. Every row comes back as `'user'` - the value the column
had for every account on every deployment that was not using it.
"""

import sqlalchemy as sa

from alembic import op

revision = "0066_drop_users_role"
down_revision = "0065_env_observability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("users", "role")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=50), nullable=False, server_default="user"),
    )
