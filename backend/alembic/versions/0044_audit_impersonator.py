"""An audit entry records who was acting behind the actor.

An impersonated request is attributed to the account it acts *as* - its token's
`sub` is the target - so every row it writes and every action it records named
the target and nobody else. An administrator who read a customer's conversation
and one who deleted their agent left the same trace: the customer's own.

So the actor behind the actor is stored. `impersonator_user_id` is the
administrator an `act` claim on the token names, written by `record_audit` from
the request's audit context (#943). Null on an ordinary request, where nobody is
acting as anybody else, and nothing is backfilled - there is no way to know after
the fact whether a past action was impersonated, and guessing one would be a
false accusation rather than a missing one.

Revision ID: 0044_audit_impersonator
Revises: 0043_rag_document_source_path
Create Date: 2026-08-20

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0044_audit_impersonator"
down_revision: str | None = "0043_rag_document_source_path"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_admin_audit_logs",
        sa.Column("impersonator_user_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "app_admin_audit_logs_impersonator_user_id_idx",
        "app_admin_audit_logs",
        ["impersonator_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "app_admin_audit_logs_impersonator_user_id_idx",
        table_name="app_admin_audit_logs",
    )
    op.drop_column("app_admin_audit_logs", "impersonator_user_id")
