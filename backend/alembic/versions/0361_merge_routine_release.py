"""Join routine histories with the eval and knowledge-coverage release train.

Retain the existing routine and evaluation revision identities for upgrades.
"""

revision: str = "0361_merge_routine_release"
down_revision: tuple[str, str] = (
    "0357_merge_routines_and_checks",
    "0360_merge_key_coverage",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
