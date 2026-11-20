"""Join personal models, app connections, and Drive OAuth without rewriting history.

The native Claude deployment already holds personal model ownership at 0296.
App connections descend from the parallel 0297 agent-message revision, and
Drive OAuth has its own 0296 branch. Keeping all three parents lets each
deployment apply only its missing additive changes; this merge itself changes
no tables, credentials, or ownership data.
"""

revision: str = "0299_merge_personal_composio"
down_revision: tuple[str, str, str] = (
    "0296_personal_model_connections",
    "0298_composio_connections",
    "0296_gdrive_oauth",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
