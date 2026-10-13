"""Datasets: the versioned test cases an agent's evals run over.

Four tables, because a version has to stay readable after the cases it held are
edited: `datasets` is the shareable resource, `dataset_cases` holds immutable case
revisions, `dataset_versions` numbers each change, and `dataset_version_cases`
says which revisions a version holds. A snapshot column per version was the
alternative; it copies every case's text on every one-case edit, where a
membership row copies sixteen bytes of id. Nothing existing is touched, so the
downgrade drops the four tables and loses only what was written into them.

Revision ID: 0106_datasets
Revises: 0105_workspace_directories
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0106_datasets"
down_revision: str | None = "0105_workspace_directories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=True),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("latest_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("case_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "visibility IN ('private', 'team', 'org')",
            name=op.f("datasets_ck_dataset_visibility_check"),
        ),
        sa.CheckConstraint("case_count >= 0", name=op.f("datasets_ck_dataset_case_count_check")),
        sa.CheckConstraint(
            "latest_version >= 0", name=op.f("datasets_ck_dataset_latest_version_check")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("datasets_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("datasets_owner_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("datasets_pkey")),
        sa.UniqueConstraint("organization_id", "name", name="uq_dataset_org_name"),
    )
    op.create_index(
        op.f("datasets_organization_id_idx"), "datasets", ["organization_id"], unique=False
    )
    op.create_index(op.f("datasets_owner_user_id_idx"), "datasets", ["owner_user_id"], unique=False)
    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("dataset_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("change", sa.String(length=16), nullable=False),
        sa.Column("changed_cases", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "change IN ('add', 'edit', 'remove', 'import')",
            name=op.f("dataset_versions_ck_dataset_version_change_check"),
        ),
        sa.CheckConstraint(
            "case_count >= 0", name=op.f("dataset_versions_ck_dataset_version_case_count_check")
        ),
        sa.CheckConstraint(
            "changed_cases >= 0",
            name=op.f("dataset_versions_ck_dataset_version_changed_cases_check"),
        ),
        sa.CheckConstraint(
            "number >= 1", name=op.f("dataset_versions_ck_dataset_version_number_check")
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("dataset_versions_created_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name=op.f("dataset_versions_dataset_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("dataset_versions_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("dataset_versions_pkey")),
        sa.UniqueConstraint("dataset_id", "number", name="uq_dataset_version_number"),
    )
    op.create_index(
        op.f("dataset_versions_dataset_id_idx"), "dataset_versions", ["dataset_id"], unique=False
    )
    op.create_index(
        op.f("dataset_versions_organization_id_idx"),
        "dataset_versions",
        ["organization_id"],
        unique=False,
    )
    op.create_table(
        "dataset_cases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("dataset_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column(
            "history", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
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
            "checks", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column(
            "tags", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_run_id", sa.UUID(), nullable=True),
        sa.Column("source_conversation_id", sa.UUID(), nullable=True),
        sa.Column("source_message_id", sa.UUID(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'import', 'conversation', 'synthetic')",
            name=op.f("dataset_cases_ck_dataset_case_source_check"),
        ),
        sa.CheckConstraint(
            "order_mode IN ('any', 'in_order', 'exact')",
            name=op.f("dataset_cases_ck_dataset_case_order_mode_check"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("dataset_cases_created_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name=op.f("dataset_cases_dataset_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("dataset_cases_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_conversation_id"],
            ["conversations.id"],
            name=op.f("dataset_cases_source_conversation_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_message_id"],
            ["messages.id"],
            name=op.f("dataset_cases_source_message_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id"],
            ["agent_runs.id"],
            name=op.f("dataset_cases_source_run_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("dataset_cases_pkey")),
    )
    op.create_index(op.f("dataset_cases_case_id_idx"), "dataset_cases", ["case_id"], unique=False)
    op.create_index(
        op.f("dataset_cases_dataset_id_idx"), "dataset_cases", ["dataset_id"], unique=False
    )
    op.create_index(
        op.f("dataset_cases_organization_id_idx"),
        "dataset_cases",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("dataset_cases_source_conversation_id_idx"),
        "dataset_cases",
        ["source_conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("dataset_cases_source_message_id_idx"),
        "dataset_cases",
        ["source_message_id"],
        unique=False,
    )
    op.create_index(
        op.f("dataset_cases_source_run_id_idx"), "dataset_cases", ["source_run_id"], unique=False
    )
    op.create_table(
        "dataset_version_cases",
        sa.Column("version_id", sa.UUID(), nullable=False),
        sa.Column("case_revision_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_revision_id"],
            ["dataset_cases.id"],
            name=op.f("dataset_version_cases_case_revision_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["dataset_versions.id"],
            name=op.f("dataset_version_cases_version_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "version_id", "case_revision_id", name=op.f("dataset_version_cases_pkey")
        ),
    )
    op.create_index(
        op.f("dataset_version_cases_case_revision_id_idx"),
        "dataset_version_cases",
        ["case_revision_id"],
        unique=False,
    )
    op.create_index(
        "ix_dataset_version_cases_order",
        "dataset_version_cases",
        ["version_id", "position"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_dataset_version_cases_order", table_name="dataset_version_cases")
    op.drop_index(
        op.f("dataset_version_cases_case_revision_id_idx"), table_name="dataset_version_cases"
    )
    op.drop_table("dataset_version_cases")
    op.drop_index(op.f("dataset_cases_source_run_id_idx"), table_name="dataset_cases")
    op.drop_index(op.f("dataset_cases_source_message_id_idx"), table_name="dataset_cases")
    op.drop_index(op.f("dataset_cases_source_conversation_id_idx"), table_name="dataset_cases")
    op.drop_index(op.f("dataset_cases_organization_id_idx"), table_name="dataset_cases")
    op.drop_index(op.f("dataset_cases_dataset_id_idx"), table_name="dataset_cases")
    op.drop_index(op.f("dataset_cases_case_id_idx"), table_name="dataset_cases")
    op.drop_table("dataset_cases")
    op.drop_index(op.f("dataset_versions_organization_id_idx"), table_name="dataset_versions")
    op.drop_index(op.f("dataset_versions_dataset_id_idx"), table_name="dataset_versions")
    op.drop_table("dataset_versions")
    op.drop_index(op.f("datasets_owner_user_id_idx"), table_name="datasets")
    op.drop_index(op.f("datasets_organization_id_idx"), table_name="datasets")
    op.drop_table("datasets")
