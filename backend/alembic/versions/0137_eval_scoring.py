"""Eval scoring: system agents, the AI assistance switch and case scores.

`agents.system_key` marks an agent the platform seeded and starts itself - the
eval judge first, the case generator and the authoring assistant after it. A key
rather than a reserved slug, because the slug derives from a name the organization
may change, and a person's own agent may already hold it. The partial unique index
gives each organization at most one agent per key; ordinary agents leave it null.
No existing agent becomes a system agent: one is seeded the first time something
needs it. `agents.kind` says what an agent is for: `agent` for every existing
one, `judge` for the seeded judge and each judge a dataset gets of its own.

`organizations.ai_assistance_enabled` is the one switch for every model-backed
eval and authoring feature. Off by default, for every organization the migration
finds as for every new one: whether models judge and draft here is the
organization's decision, so nothing model-backed runs until an admin turns it on.

`datasets.scoring` holds how a dataset's cases are scored. It is not versioned
with the cases - how a team grades is not what it asks - so `case_scores` keeps
the configuration each score was computed with beside its results, and which
judge graded it - model profile, spec version, rubric hash. A score
outlives the run it read (`SET NULL`), so it keeps the answer it scored, and a
person's verdict lives in its own columns so it never overwrites what the judge
said. `eval_run_id` names the eval run that scored it; eval runs come in a
later migration, which adds its foreign key.

Nothing existing changes meaning, so the downgrade drops what was added and loses
which agents were seeded, whether an organization had switched AI assistance
off, every dataset's scoring configuration and every score.

Revision ID: 0137_eval_scoring
Revises: 0136_environment_connections
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0137_eval_scoring"
down_revision: str | None = "0136_environment_connections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "ai_assistance_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("agents", sa.Column("system_key", sa.String(length=64), nullable=True))
    op.add_column(
        "agents",
        sa.Column("kind", sa.String(length=16), server_default="agent", nullable=False),
    )
    op.create_check_constraint("ck_agent_kind", "agents", "kind IN ('agent', 'judge')")
    op.create_index(
        "uq_agents_org_system_key",
        "agents",
        ["organization_id", "system_key"],
        unique=True,
        postgresql_where=sa.text("system_key IS NOT NULL"),
    )
    op.add_column(
        "datasets",
        sa.Column(
            "scoring",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )
    op.create_table(
        "case_scores",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("dataset_id", sa.UUID(), nullable=False),
        sa.Column("case_revision_id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("eval_run_id", sa.UUID(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("scoring", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("judge", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("review_state", sa.String(length=16), server_default="none", nullable=False),
        sa.Column("human_passed", sa.Boolean(), nullable=True),
        sa.Column("human_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "review_state IN ('none', 'pending', 'done')",
            name=op.f("case_scores_ck_case_score_review_state_check"),
        ),
        sa.ForeignKeyConstraint(
            ["case_revision_id"],
            ["dataset_cases.id"],
            name=op.f("case_scores_case_revision_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("case_scores_created_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name=op.f("case_scores_dataset_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("case_scores_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            name=op.f("case_scores_reviewed_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("case_scores_run_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("case_scores_pkey")),
    )
    op.create_index(op.f("case_scores_case_id_idx"), "case_scores", ["case_id"], unique=False)
    op.create_index(
        op.f("case_scores_case_revision_id_idx"), "case_scores", ["case_revision_id"], unique=False
    )
    op.create_index(
        op.f("case_scores_organization_id_idx"), "case_scores", ["organization_id"], unique=False
    )
    op.create_index(op.f("case_scores_run_id_idx"), "case_scores", ["run_id"], unique=False)
    op.create_index(
        op.f("case_scores_eval_run_id_idx"), "case_scores", ["eval_run_id"], unique=False
    )
    op.create_index(
        "ix_case_scores_dataset_created", "case_scores", ["dataset_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_case_scores_org_review",
        "case_scores",
        ["organization_id", "review_state"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("case_scores")
    op.drop_column("datasets", "scoring")
    op.drop_index("uq_agents_org_system_key", table_name="agents")
    op.drop_constraint("ck_agent_kind", "agents", type_="check")
    op.drop_column("agents", "kind")
    op.drop_column("agents", "system_key")
    op.drop_column("organizations", "ai_assistance_enabled")
