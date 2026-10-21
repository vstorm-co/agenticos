"""Knowledge gaps read from answers: a signal on each miss, and the answers read.

`knowledge_searches` gains `signal` - `retrieval` for every search already
recorded, `answer` or `rating` for an answer a model read as a miss - and
`message_id`, the answer such a row was read from, unique with the knowledge
base so an answer is a miss at most once in each. `knowledge_gap_classifications`
remembers every answer read for each knowledge base, with the verdict and the
classifier's run, and holds no text.

`agents.kind` gains `classifier`, the kind of the system agent that reads them.
The downgrade makes such an agent an ordinary one and clears its `system_key`,
so an upgrade seeds a fresh classifier, deletes the misses read from answers -
which were never searches - and drops what this revision added.

Revision ID: 0153_knowledge_gap_signals
Revises: 0150_case_generation
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0153_knowledge_gap_signals"
down_revision: str | None = "0150_case_generation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The kinds `ck_agent_kind` allows at the revision this one follows.
_KINDS_BEFORE = ("agent", "judge", "drafter", "generator")


def _kinds(kinds: Sequence[str]) -> str:
    return "kind IN (" + ", ".join(f"'{kind}'" for kind in kinds) + ")"


def upgrade() -> None:
    op.drop_constraint("ck_agent_kind", "agents", type_="check")
    op.create_check_constraint("ck_agent_kind", "agents", _kinds((*_KINDS_BEFORE, "classifier")))
    op.add_column(
        "knowledge_searches",
        sa.Column("signal", sa.String(length=16), server_default="retrieval", nullable=False),
    )
    op.add_column("knowledge_searches", sa.Column("message_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("knowledge_searches_message_id_fkey"),
        "knowledge_searches",
        "messages",
        ["message_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "uq_knowledge_searches_message_id",
        "knowledge_searches",
        ["message_id", "knowledge_base_ids"],
        unique=True,
        postgresql_where=sa.text("message_id IS NOT NULL"),
    )
    op.create_check_constraint(
        op.f("knowledge_searches_ck_knowledge_search_signal_check"),
        "knowledge_searches",
        "signal IN ('retrieval', 'answer', 'rating')",
    )
    op.create_table(
        "knowledge_gap_classifications",
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("knowledge_base_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("signal", sa.String(length=16), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column(
            "classified_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "signal IN ('answer', 'rating', 'none')",
            name=op.f("knowledge_gap_classifications_ck_classification_signal_check"),
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name=op.f("knowledge_gap_classifications_message_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            name=op.f("knowledge_gap_classifications_knowledge_base_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("knowledge_gap_classifications_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("knowledge_gap_classifications_run_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "message_id", "knowledge_base_id", name=op.f("knowledge_gap_classifications_pkey")
        ),
    )
    op.create_index(
        op.f("knowledge_gap_classifications_organization_id_idx"),
        "knowledge_gap_classifications",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("knowledge_gap_classifications_run_id_idx"),
        "knowledge_gap_classifications",
        ["run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.execute("UPDATE agents SET kind = 'agent', system_key = NULL WHERE kind = 'classifier'")
    op.drop_constraint("ck_agent_kind", "agents", type_="check")
    op.create_check_constraint("ck_agent_kind", "agents", _kinds(_KINDS_BEFORE))
    op.drop_index(
        op.f("knowledge_gap_classifications_run_id_idx"),
        table_name="knowledge_gap_classifications",
    )
    op.drop_index(
        op.f("knowledge_gap_classifications_organization_id_idx"),
        table_name="knowledge_gap_classifications",
    )
    op.drop_table("knowledge_gap_classifications")
    op.execute("DELETE FROM knowledge_searches WHERE signal <> 'retrieval'")
    op.drop_constraint(
        op.f("knowledge_searches_ck_knowledge_search_signal_check"),
        "knowledge_searches",
        type_="check",
    )
    op.drop_index("uq_knowledge_searches_message_id", table_name="knowledge_searches")
    op.drop_constraint(
        op.f("knowledge_searches_message_id_fkey"), "knowledge_searches", type_="foreignkey"
    )
    op.drop_column("knowledge_searches", "message_id")
    op.drop_column("knowledge_searches", "signal")
