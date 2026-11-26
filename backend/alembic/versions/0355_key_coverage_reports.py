"""Which of a dataset's keys none of an agent's sources covers, and the agent that judges it.

`key_coverage_reports` holds, for one agent and one dataset, a verdict per key
label - covered, not covered or unsure - with the sources that hold it. Labels and
source names only, never a key's value. One per agent and dataset. `agents.kind`
gains `coverage`, the kind of that system agent.

The downgrade drops the reports and turns coverage agents into ordinary ones
before narrowing the kinds again, as 0168_authoring_proposals.py does.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0355_key_coverage_reports"
down_revision: str = "0354_case_key_drafts"
branch_labels: None = None
depends_on: None = None

_KINDS = (
    "kind IN ('agent', 'judge', 'drafter', 'generator', 'classifier', 'improver', 'extractor', "
    "'coverage')"
)
# The kinds `ck_agent_kind` allows at the revision this one follows.
_KINDS_BEFORE = (
    "kind IN ('agent', 'judge', 'drafter', 'generator', 'classifier', 'improver', 'extractor')"
)


def upgrade() -> None:
    op.drop_constraint("ck_agent_kind", "agents", type_="check")
    op.create_check_constraint("ck_agent_kind", "agents", _KINDS)
    op.create_table(
        "key_coverage_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dataset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dataset_version", sa.Integer(), nullable=False),
        sa.Column(
            "requested_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by_api_key_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("items", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("unseen_sources", sa.Integer(), nullable=False),
        sa.Column("judged_sources", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("source_marks", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("agent_id", "dataset_id", name="uq_key_coverage_report_pair"),
        sa.CheckConstraint(
            "status IN ('running', 'ready', 'failed')", name="ck_key_coverage_report_status"
        ),
        sa.CheckConstraint("unseen_sources >= 0", name="ck_key_coverage_report_unseen"),
    )
    for column in ("organization_id", "agent_version_id", "dataset_id", "run_id"):
        op.create_index(f"key_coverage_reports_{column}_idx", "key_coverage_reports", [column])


def downgrade() -> None:
    op.drop_table("key_coverage_reports")
    op.drop_constraint("ck_agent_kind", "agents", type_="check")
    op.execute("UPDATE agents SET kind = 'agent', system_key = NULL WHERE kind = 'coverage'")
    op.create_check_constraint("ck_agent_kind", "agents", _KINDS_BEFORE)
