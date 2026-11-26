"""Read an improvement session's eval answers for missing knowledge.

A session sorts the bad answers it learns from into missing knowledge and the
agent's own faults. It read only chat answers, because the classifier's verdicts
and the misses it records are keyed on a message, and an eval answer has none.
A session that learned from eval answers alone therefore never found a topic.

`knowledge_gap_eval_classifications` keeps a verdict on an eval answer by the run
that gave it, as `knowledge_gap_classifications` does by message. A miss read
from one is a `knowledge_searches` row with no message, unique per run and
knowledge base, so a second read records none.

`knowledge_searches.subject` is what a miss read from an answer lacks, as the
classifier named it - "Lead times by product" rather than one customer's question -
so its topic is grouped and named by it. Earlier misses have none and stay grouped
and named by their question.

**Downgrade** drops the table, the index and the column, and the misses read from
eval answers with them: without the index nothing keeps them to one per run.

Revision ID: 0352_eval_answer_gaps
Revises: 0351_skill_check_too_few
Create Date: 2026-11-20
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0352_eval_answer_gaps"
down_revision: str = "0351_skill_check_too_few"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_gap_eval_classifications",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signal", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("classifier_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "classified_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "signal IN ('answer', 'rating', 'none', 'refused')",
            name=op.f("knowledge_gap_eval_classifications_ck_eval_classification_signal_check"),
        ),
        sa.ForeignKeyConstraint(
            ["classifier_run_id"],
            ["agent_runs.id"],
            name=op.f("knowledge_gap_eval_classifications_classifier_run_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            name=op.f("knowledge_gap_eval_classifications_knowledge_base_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("knowledge_gap_eval_classifications_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("knowledge_gap_eval_classifications_run_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "run_id", "knowledge_base_id", name=op.f("knowledge_gap_eval_classifications_pkey")
        ),
    )
    op.create_index(
        op.f("knowledge_gap_eval_classifications_classifier_run_id_idx"),
        "knowledge_gap_eval_classifications",
        ["classifier_run_id"],
    )
    op.create_index(
        op.f("knowledge_gap_eval_classifications_organization_id_idx"),
        "knowledge_gap_eval_classifications",
        ["organization_id"],
    )
    op.add_column("knowledge_searches", sa.Column("subject", sa.Text(), nullable=True))
    op.create_index(
        "uq_knowledge_searches_eval_answer",
        "knowledge_searches",
        ["run_id", "knowledge_base_ids"],
        unique=True,
        postgresql_where=sa.text("message_id IS NULL AND signal <> 'retrieval'"),
    )


def downgrade() -> None:
    op.execute("DELETE FROM knowledge_searches WHERE message_id IS NULL AND signal <> 'retrieval'")
    op.drop_index("uq_knowledge_searches_eval_answer", table_name="knowledge_searches")
    op.drop_column("knowledge_searches", "subject")
    op.drop_index(
        op.f("knowledge_gap_eval_classifications_organization_id_idx"),
        table_name="knowledge_gap_eval_classifications",
    )
    op.drop_index(
        op.f("knowledge_gap_eval_classifications_classifier_run_id_idx"),
        table_name="knowledge_gap_eval_classifications",
    )
    op.drop_table("knowledge_gap_eval_classifications")
