"""A call an isolated run held because it would reach outside the deployment says so.

Isolated runs used to execute every tool that declared it only reads. A read can
still carry data out - a fetched URL, a search query, a remote agent's task - so
such calls are now held too, and recorded with the reason `external` beside
`writes` and `needs_approval`.

Downgrade records them as `writes`: the older check knows no other reason for a
call that was not executed, and `blocked` is what each of them still was.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0365_intercepted_call_external"
down_revision: str | None = "0364_merge_routine_and_kb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_intercepted_tool_call_reason"
_TABLE = "intercepted_tool_calls"


def _reasons(reasons: str) -> str:
    return (
        f"(outcome = 'blocked' AND reason IS NOT NULL AND reason IN ({reasons})) "
        "OR (outcome <> 'blocked' AND reason IS NULL)"
    )


def upgrade() -> None:
    op.drop_constraint(_CHECK, _TABLE, type_="check")
    op.create_check_constraint(_CHECK, _TABLE, _reasons("'writes', 'needs_approval', 'external'"))


def downgrade() -> None:
    op.drop_constraint(_CHECK, _TABLE, type_="check")
    op.execute(f"UPDATE {_TABLE} SET reason = 'writes' WHERE reason = 'external'")
    op.create_check_constraint(_CHECK, _TABLE, _reasons("'writes', 'needs_approval'"))
