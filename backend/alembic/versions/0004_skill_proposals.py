"""Skill changes an agent proposed, waiting for a person to decide

Revision ID: 0004_skill_proposals
Revises: 0003_sandbox_connections
Create Date: 2026-08-03

An agent with a workspace gets its skills as files, which is what makes a skill's
script runnable at all - it is on disk beside the shell that can run it. Writable
files follow, and this table is where the writes land.

They land here rather than in `skills` because a skill is instructions every agent
bound to it follows on every run. An agent that could edit one directly could
rewrite what another agent does, inside a conversation nobody is reviewing, and
the next reader would have no way to tell a considered improvement from a
hallucinated one. So: recorded here, accepted by somebody holding `skills:edit`,
and `skills.version` moves only then.

The body is stored whole rather than as a diff. A proposal has to be applicable
weeks later, after the skill may itself have moved; a diff would either fail to
apply or apply where it was never meant to, while two complete versions make the
conflict visible to the person deciding.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004_skill_proposals"
down_revision = "0003_sandbox_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("resources", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("decided_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        # CASCADE: a proposal against a deleted skill has nothing left to apply
        # to, and keeping it would offer a reviewer a change to a skill that is
        # gone.
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skills.id"], name="skill_proposals_skill_id_fkey", ondelete="CASCADE"
        ),
        # SET NULL for the agent and the conversation: the proposal is a record
        # of what happened, and deleting either does not unmake it.
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name="skill_proposals_agent_id_fkey", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="skill_proposals_conversation_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            name="skill_proposals_decided_by_user_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="skill_proposals_organization_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="skill_proposals_pkey"),
    )
    op.create_index(
        op.f("ix_skill_proposals_organization_id"),
        "skill_proposals",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_skill_proposals_skill_id"), "skill_proposals", ["skill_id"], unique=False
    )
    op.create_index(
        op.f("ix_skill_proposals_agent_id"), "skill_proposals", ["agent_id"], unique=False
    )
    op.create_index(op.f("ix_skill_proposals_status"), "skill_proposals", ["status"], unique=False)
    # A reviewer's only query: what is waiting, in this organization. Composite
    # because filtering on status alone scans every proposal ever decided.
    op.create_index(
        "ix_skill_proposals_pending", "skill_proposals", ["organization_id", "status"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_skill_proposals_pending", table_name="skill_proposals")
    op.drop_index(op.f("ix_skill_proposals_status"), table_name="skill_proposals")
    op.drop_index(op.f("ix_skill_proposals_agent_id"), table_name="skill_proposals")
    op.drop_index(op.f("ix_skill_proposals_skill_id"), table_name="skill_proposals")
    op.drop_index(op.f("ix_skill_proposals_organization_id"), table_name="skill_proposals")
    op.drop_table("skill_proposals")
