"""Keys drafted from a case's reference answer, and the agent that drafts them.

`case_key_drafts` holds what the key extractor listed for one case - the facts its
reference answer holds, each as a label and a value - until a person uses or
dismisses it. One per case. `agents.kind` gains `extractor`, the kind of that
system agent, so it is not offered where a case generator is.

The downgrade drops the drafts and turns extractor agents into ordinary ones
before narrowing the kinds again, as 0168_authoring_proposals.py does.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0354_case_key_drafts"
down_revision: str = "0353_skill_check_verdict_version"
branch_labels: None = None
depends_on: None = None

_KINDS = "kind IN ('agent', 'judge', 'drafter', 'generator', 'classifier', 'improver', 'extractor')"
# The kinds `ck_agent_kind` allows at the revision this one follows.
_KINDS_BEFORE = "kind IN ('agent', 'judge', 'drafter', 'generator', 'classifier', 'improver')"


def upgrade() -> None:
    op.drop_constraint("ck_agent_kind", "agents", type_="check")
    op.create_check_constraint("ck_agent_kind", "agents", _KINDS)
    op.create_table(
        "case_key_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dataset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dataset_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by_api_key_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("keys", postgresql.JSONB(), nullable=False, server_default="[]"),
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
        sa.UniqueConstraint("dataset_id", "case_id", name="uq_case_key_draft_case"),
        sa.CheckConstraint(
            "status IN ('running', 'ready', 'failed')", name="ck_case_key_draft_status"
        ),
    )
    op.create_index("case_key_drafts_organization_id_idx", "case_key_drafts", ["organization_id"])
    op.create_index("case_key_drafts_revision_id_idx", "case_key_drafts", ["revision_id"])
    op.create_index("case_key_drafts_run_id_idx", "case_key_drafts", ["run_id"])


def downgrade() -> None:
    op.drop_table("case_key_drafts")
    op.drop_constraint("ck_agent_kind", "agents", type_="check")
    op.execute("UPDATE agents SET kind = 'agent', system_key = NULL WHERE kind = 'extractor'")
    op.create_check_constraint("ck_agent_kind", "agents", _KINDS_BEFORE)
