"""Let a deleted user keep their invite audit trail instead of blocking deletion.

Three foreign keys into `users.id` - who invited a member, who authored an
invitation, who accepted one - carried no `ondelete`, so PostgreSQL's NO ACTION
made any of them an absolute bar on deleting the referenced user. #9 reconciled
the CHECK-versus-cascade collisions for a normally-registered user, but a user
who had ever invited another member still failed `DELETE /users/{id}` with a
foreign-key violation surfaced as a 500 (#1110).

`SET NULL` on all three: who invited a member and who accepted an invitation are
audit context that should outlive the user, the way the secret and
knowledge-base attribution FKs already null. `invitations.invited_by_user_id`
was NOT NULL, so it is made nullable in the same step - it is set on every create
and null only once the inviter is gone.

The downgrade re-tightens that column to NOT NULL, which fails if the SET NULL
schema has run long enough for an inviter to be deleted and left a null behind -
the standard nullable->NOT NULL rollback risk, no data loss, and it aborts
cleanly.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0059_invite_fk_ondelete"
down_revision: str | Sequence[str] | None = "0058_backfill_rag_lookup_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "organization_members_invited_by_user_id_fkey", "organization_members", type_="foreignkey"
    )
    op.create_foreign_key(
        "organization_members_invited_by_user_id_fkey",
        "organization_members",
        "users",
        ["invited_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.alter_column("invitations", "invited_by_user_id", existing_type=sa.UUID(), nullable=True)
    op.drop_constraint("invitations_invited_by_user_id_fkey", "invitations", type_="foreignkey")
    op.create_foreign_key(
        "invitations_invited_by_user_id_fkey",
        "invitations",
        "users",
        ["invited_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_constraint("invitations_accepted_by_user_id_fkey", "invitations", type_="foreignkey")
    op.create_foreign_key(
        "invitations_accepted_by_user_id_fkey",
        "invitations",
        "users",
        ["accepted_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("invitations_accepted_by_user_id_fkey", "invitations", type_="foreignkey")
    op.create_foreign_key(
        "invitations_accepted_by_user_id_fkey",
        "invitations",
        "users",
        ["accepted_by_user_id"],
        ["id"],
    )

    op.drop_constraint("invitations_invited_by_user_id_fkey", "invitations", type_="foreignkey")
    op.create_foreign_key(
        "invitations_invited_by_user_id_fkey",
        "invitations",
        "users",
        ["invited_by_user_id"],
        ["id"],
    )
    op.alter_column("invitations", "invited_by_user_id", existing_type=sa.UUID(), nullable=False)

    op.drop_constraint(
        "organization_members_invited_by_user_id_fkey", "organization_members", type_="foreignkey"
    )
    op.create_foreign_key(
        "organization_members_invited_by_user_id_fkey",
        "organization_members",
        "users",
        ["invited_by_user_id"],
        ["id"],
    )
