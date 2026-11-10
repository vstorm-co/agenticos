"""Join evaluation previews with the released platform without rewriting either history.

A deployment at either parent applies only the missing branch. The merge itself
does not change data; the evaluation revisions preserve existing queued helpers.
"""

revision: str = "0304_merge_evals_platform"
down_revision: tuple[str, str] = ("0296_merge_evals_main", "0303_merge_workflow_onboarding")
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
