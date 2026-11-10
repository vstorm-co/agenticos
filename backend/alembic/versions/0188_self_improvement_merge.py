"""Join the self-improvement branches into one migration head.

Each parent belongs to a separately reviewed part of the milestone. Keep those
revisions intact so a deployment that applied any part can reach the combined
schema without replaying it. This revision changes no tables; upgrade applies
all outstanding parent branches, and downgrade only separates their heads.

Revision ID: 0188_self_improvement_merge
Revises: the eight self-improvement branch heads
Create Date: 2026-10-24
"""

from collections.abc import Sequence

revision: str = "0188_self_improvement_merge"
down_revision: tuple[str, ...] = (
    "0174_case_score_agent_key",
    "0177_dataset_case_anonymised_at",
    "0181_dataset_agent_auto_accept",
    "0182_eval_suite_pin",
    "0183_proposal_revision",
    "0184_eval_run_pinned_baseline",
    "0186_knowledge_gap_causes",
    "0187_job_api_key",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
