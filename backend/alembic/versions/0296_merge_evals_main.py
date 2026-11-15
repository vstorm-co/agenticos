"""Join the evaluation workspace and current platform migrations.

Both histories have already been issued. Keep their revisions intact so a
preview deployment and a released installation apply only their missing branch.
"""

revision: str = "0296_merge_evals_main"
down_revision: tuple[str, str] = ("0254_merge_eval_rag_index", "0295_tool_approval_consent")
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
