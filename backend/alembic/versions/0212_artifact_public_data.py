"""A page owner's consent to show its data to anyone with the link (#1975).

Four columns on `artifacts` record that consent: the digest of the page queries it was
given to (`public_data_fingerprint`), who gave it, the owner's membership it is valid
under (`public_data_membership_id`, no foreign key - as `consented_by_membership_id` has
none, a membership that is gone must read as a consent that no longer holds, not block
its removal) and when.

`ck_artifact_public_data_membership` keeps a consent from naming nobody: a fingerprint is
set only together with the membership it was given under.

Revision ID: 0212_artifact_public_data
Revises: 0211_org_public_live_data
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0212_artifact_public_data"
down_revision: str | Sequence[str] | None = "0211_org_public_live_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_artifact_public_data_membership"
_INDEX = "artifacts_public_data_by_user_id_idx"


def upgrade() -> None:
    op.add_column("artifacts", sa.Column("public_data_fingerprint", sa.String(64), nullable=True))
    op.add_column(
        "artifacts",
        sa.Column(
            "public_data_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "artifacts",
        sa.Column("public_data_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "artifacts", sa.Column("public_data_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(op.f(_INDEX), "artifacts", ["public_data_by_user_id"])
    op.create_check_constraint(
        _CHECK,
        "artifacts",
        "public_data_fingerprint IS NULL OR public_data_membership_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(_CHECK, "artifacts", type_="check")
    op.drop_index(op.f(_INDEX), table_name="artifacts")
    op.drop_column("artifacts", "public_data_at")
    op.drop_column("artifacts", "public_data_membership_id")
    op.drop_column("artifacts", "public_data_by_user_id")
    op.drop_column("artifacts", "public_data_fingerprint")
