"""Join native subscription accounts with the routine and evaluation release train.

Preserve both applied migration histories and expose one deployment head.
"""

revision: str = "0362_merge_native_release"
down_revision: tuple[str, str] = (
    "0358_merge_native_and_checks",
    "0361_merge_routine_release",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
