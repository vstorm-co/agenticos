"""Join routine chat histories and skill checks without rewriting applied revisions.

Both branches may already be applied on preview databases. This merge preserves
their identities and gives deployments one upgrade head without changing data.
"""

revision: str = "0357_merge_routines_and_checks"
down_revision: tuple[str, str] = (
    "0351_routine_chat_modes",
    "0353_skill_check_verdict_version",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
