"""Join exact routine budget storage with the combined reviewed release train.

This merge records both branch heads without changing their data. Downgrading
this metadata revision alone leaves the individual branch changes applied.
"""

from collections.abc import Sequence

revision: str = "0381_merge_currency_precision"
down_revision: tuple[str, ...] = (
    "0380_merge_currency_reviewed",
    "0379_trigger_budget_precision",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
