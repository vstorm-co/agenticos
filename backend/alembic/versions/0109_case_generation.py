"""Case generation: drafted test cases waiting for a person's decision.

`case_generations` records each request to draft cases for a dataset and the
generator run that drafted them; `case_proposals` holds what it drafted until
somebody accepts or dismisses it. A decision deletes the proposal - an accepted
one lives on as a case in a new dataset version, a dismissed one leaves nothing -
so the generation keeps the counts instead.

Two changes reach the datasets tables. `dataset_cases.source_document_id` links a
case drafted from a knowledge passage to its document, the way
`source_message_id` links one taken from a conversation; `SET NULL`, because the
passage was copied into the case. And `generate` joins the version change kinds,
so a dataset's history says which version came from accepted drafts.

The downgrade drops both tables and the column, and rewrites `generate` versions
as `add` before restoring the narrower CHECK - what those versions did is still
true, only the label is lost.

Revision ID: 0109_case_generation
Revises: 0106_datasets
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0109_case_generation"
down_revision: str | None = "0106_datasets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "case_generations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("dataset_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("requested_by_user_id", sa.UUID(), nullable=True),
        sa.Column("sources", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("proposed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("accepted_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("dismissed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'ready', 'failed')",
            name=op.f("case_generations_ck_case_generation_status_check"),
        ),
        sa.CheckConstraint(
            "requested_count >= 1",
            name=op.f("case_generations_ck_case_generation_requested_count_check"),
        ),
        sa.CheckConstraint(
            "proposed_count >= 0 AND accepted_count >= 0 AND dismissed_count >= 0",
            name=op.f("case_generations_ck_case_generation_counts_check"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("case_generations_agent_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name=op.f("case_generations_dataset_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("case_generations_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("case_generations_requested_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("case_generations_run_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("case_generations_pkey")),
    )
    for column in ("agent_id", "dataset_id", "organization_id", "run_id"):
        op.create_index(
            op.f(f"case_generations_{column}_idx"), "case_generations", [column], unique=False
        )

    op.create_table(
        "case_proposals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("generation_id", sa.UUID(), nullable=False),
        sa.Column("dataset_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column(
            "history",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("reference_answer", sa.Text(), nullable=True),
        sa.Column("counter_example", sa.Text(), nullable=True),
        sa.Column(
            "expected_tool_calls",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("order_mode", sa.String(length=16), server_default="any", nullable=False),
        sa.Column(
            "checks",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source_document_id", sa.UUID(), nullable=True),
        sa.Column("source_run_id", sa.UUID(), nullable=True),
        sa.Column("source_conversation_id", sa.UUID(), nullable=True),
        sa.Column("source_message_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "origin IN ('agent', 'knowledge', 'conversation', 'red_team')",
            name=op.f("case_proposals_ck_case_proposal_origin_check"),
        ),
        sa.CheckConstraint(
            "order_mode IN ('any', 'in_order', 'exact')",
            name=op.f("case_proposals_ck_case_proposal_order_mode_check"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name=op.f("case_proposals_dataset_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["generation_id"],
            ["case_generations.id"],
            name=op.f("case_proposals_generation_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("case_proposals_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_conversation_id"],
            ["conversations.id"],
            name=op.f("case_proposals_source_conversation_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["rag_documents.id"],
            name=op.f("case_proposals_source_document_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_message_id"],
            ["messages.id"],
            name=op.f("case_proposals_source_message_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id"],
            ["agent_runs.id"],
            name=op.f("case_proposals_source_run_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("case_proposals_pkey")),
    )
    for column in (
        "dataset_id",
        "generation_id",
        "organization_id",
        "source_conversation_id",
        "source_document_id",
        "source_message_id",
        "source_run_id",
    ):
        op.create_index(
            op.f(f"case_proposals_{column}_idx"), "case_proposals", [column], unique=False
        )

    op.add_column("dataset_cases", sa.Column("source_document_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("dataset_cases_source_document_id_fkey"),
        "dataset_cases",
        "rag_documents",
        ["source_document_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("dataset_cases_source_document_id_idx"),
        "dataset_cases",
        ["source_document_id"],
        unique=False,
    )

    op.drop_constraint(
        op.f("dataset_versions_ck_dataset_version_change_check"), "dataset_versions", type_="check"
    )
    op.create_check_constraint(
        op.f("dataset_versions_ck_dataset_version_change_check"),
        "dataset_versions",
        "change IN ('add', 'edit', 'remove', 'import', 'generate')",
    )


def downgrade() -> None:
    op.execute("UPDATE dataset_versions SET change = 'add' WHERE change = 'generate'")
    op.drop_constraint(
        op.f("dataset_versions_ck_dataset_version_change_check"), "dataset_versions", type_="check"
    )
    op.create_check_constraint(
        op.f("dataset_versions_ck_dataset_version_change_check"),
        "dataset_versions",
        "change IN ('add', 'edit', 'remove', 'import')",
    )

    op.drop_index(op.f("dataset_cases_source_document_id_idx"), table_name="dataset_cases")
    op.drop_constraint(
        op.f("dataset_cases_source_document_id_fkey"), "dataset_cases", type_="foreignkey"
    )
    op.drop_column("dataset_cases", "source_document_id")

    for column in (
        "source_run_id",
        "source_message_id",
        "source_document_id",
        "source_conversation_id",
        "organization_id",
        "generation_id",
        "dataset_id",
    ):
        op.drop_index(op.f(f"case_proposals_{column}_idx"), table_name="case_proposals")
    op.drop_table("case_proposals")

    for column in ("run_id", "organization_id", "dataset_id", "agent_id"):
        op.drop_index(op.f(f"case_generations_{column}_idx"), table_name="case_generations")
    op.drop_table("case_generations")
