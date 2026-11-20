"""Store app favourites per reader so each person's Apps list stays private."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0303_artifact_favourites"
down_revision: str | None = "0302_merge_upstream"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifact_favourites",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifacts.id"],
            name=op.f("artifact_favourites_artifact_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("artifact_favourites_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "artifact_id", name=op.f("artifact_favourites_pkey")),
    )
    op.create_index(
        op.f("artifact_favourites_artifact_id_idx"),
        "artifact_favourites",
        ["artifact_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("artifact_favourites_artifact_id_idx"), table_name="artifact_favourites")
    op.drop_table("artifact_favourites")
