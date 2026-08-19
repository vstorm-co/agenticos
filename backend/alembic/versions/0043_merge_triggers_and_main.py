"""Join the triggers chain to main's - two heads, no schema change of its own

Revision ID: 0043_merge_triggers_and_main
Revises: ('0041_invitation_reservations', '0042_trigger_fire_in_flight')
Create Date: 2026-08-19

`feat/agent-triggers` numbered 0037 through 0042 while main numbered 0037 through
0041 independently, so a tree holding both has two heads and `alembic upgrade head`
refuses to choose. This merge revision is that choice and nothing else: the two
chains touch disjoint tables, so neither side needs an operation here.

Written to make the stack testable against current main. When #537 is rebased for
merge this file is expected to be dropped and its migrations renumbered onto main's
chain instead.
"""

from collections.abc import Sequence

revision: str = "0043_merge_triggers_and_main"
down_revision: tuple[str, ...] = ("0041_invitation_reservations", "0042_trigger_fire_in_flight")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to do - the merge is the revision graph, not a schema change."""


def downgrade() -> None:
    """Nothing to undo - splitting the graph again is what `downgrade` to either head does."""
