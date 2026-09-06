"""Agent memory files — an agent's own named notes, scoped to who is listening.

The store behind the `memory_files` capability (#788). Unlike a context file
(0030), which a person authors and binds to many agents read-only, a memory note
is the agent's *own*: the agent writes and edits it through a runtime tool, and it
is addressed by its agent plus the owner it was written for, never bound by id.

Nobody else writes here, which is the line between the two features rather than a
limitation, and it is why there is no `origin` column. An operator-authored store
existed on the way to this shape and went, along with the trust tier it needed,
because it was a second mechanism for what `context` already does (#1470).

`owner_key` says whose the note is: `person:<user_id>` is one human being's,
`room:<platform>:<chat_id>` is one group chat's. It is `NOT NULL` — every note
belongs to somebody — so a name is unique within one owner's store under plain SQL
uniqueness, with none of the `NULLS NOT DISTINCT` an organization-wide store
would have needed.

Who may read a note back is a question about the *run* rather than the row, and it
is answered in `app.agents.memory_scope`.

Revision ID: 0073_agent_memory_files
Revises: 0072_impersonation_sessions
Create Date: 2026-09-01

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0073_agent_memory_files"
down_revision: str | None = "0072_impersonation_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_memory_files",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("owner_key", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("agent_memory_files_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("agent_memory_files_agent_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("agent_memory_files_pkey")),
        sa.UniqueConstraint(
            "organization_id",
            "agent_id",
            "owner_key",
            "name",
            name="uq_agent_memory_file_owner_name",
        ),
    )
    op.create_index(
        op.f("agent_memory_files_organization_id_idx"),
        "agent_memory_files",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("agent_memory_files_agent_id_idx"),
        "agent_memory_files",
        ["agent_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("agent_memory_files_agent_id_idx"), table_name="agent_memory_files")
    op.drop_index(op.f("agent_memory_files_organization_id_idx"), table_name="agent_memory_files")
    op.drop_table("agent_memory_files")
