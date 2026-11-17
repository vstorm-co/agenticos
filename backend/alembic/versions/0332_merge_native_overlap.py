"""Join native integrations and routine overlap without rewriting either history.

The parent branches change separate constraints. Both changes must run before
this common head; the join itself does not change data or schema.
"""

revision: str = "0332_merge_native_overlap"
down_revision: tuple[str, str] = (
    "0331_merge_native_integrations",
    "0331_routine_overlap_attempt",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
