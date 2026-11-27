"""Join original-currency accounting with reviewed skills and runtime changes.

This revision only joins the independently reviewed migration branches. Reverting
it leaves their schema and data changes intact; downgrade either branch explicitly.
"""

from collections.abc import Sequence

revision: str = "0380_merge_currency_reviewed"
down_revision: tuple[str, ...] = (
    "0379_merge_skill_packages",
    "0378_currency_accounting_terms",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
