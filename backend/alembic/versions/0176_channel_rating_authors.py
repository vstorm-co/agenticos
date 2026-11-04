"""Allow verified channel participants to rate without an application account.

Existing ratings keep their user author. Mattermost votes instead reference a
stable channel identity, with one vote per identity and answer, so linking an
account later cannot add another vote. Deleting either author cascades its votes.
Downgrading discards channel-authored votes; user-authored ratings are retained.

Revision ID: 0176_channel_rating_authors
Revises: 0175_profile_runs_without_key
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0176_channel_rating_authors"
down_revision: str | None = "0175_profile_runs_without_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("message_ratings", "user_id", existing_type=sa.UUID(), nullable=True)
    op.add_column("message_ratings", sa.Column("channel_identity_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("message_ratings_channel_identity_id_fkey"),
        "message_ratings",
        "channel_identities",
        ["channel_identity_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "message_ratings_channel_identity_id_idx", "message_ratings", ["channel_identity_id"]
    )
    op.create_unique_constraint(
        "uq_message_channel_rating", "message_ratings", ["message_id", "channel_identity_id"]
    )
    op.create_check_constraint(
        op.f("message_ratings_ck_rating_author_check"),
        "message_ratings",
        "(user_id IS NOT NULL) <> (channel_identity_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.execute("DELETE FROM message_ratings WHERE user_id IS NULL")
    op.drop_constraint(
        op.f("message_ratings_ck_rating_author_check"), "message_ratings", type_="check"
    )
    op.drop_constraint("uq_message_channel_rating", "message_ratings", type_="unique")
    op.drop_index("message_ratings_channel_identity_id_idx", table_name="message_ratings")
    op.drop_constraint(
        op.f("message_ratings_channel_identity_id_fkey"), "message_ratings", type_="foreignkey"
    )
    op.drop_column("message_ratings", "channel_identity_id")
    op.alter_column("message_ratings", "user_id", existing_type=sa.UUID(), nullable=False)
