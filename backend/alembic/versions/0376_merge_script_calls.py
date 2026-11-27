"""Join code-mode call capture and external-read isolation with the release history.

The already-released holdout-share revision keeps its original parent. The
external-call reason migration remains an independent branch, and the new script
call column follows the existing holdout-share revision. This join preserves all
three source identities without replaying the released holdout-share backfill.
"""

from collections.abc import Sequence

revision: str = "0376_merge_script_calls"
down_revision: tuple[str, str, str] = (
    "0375_merge_service_connections",
    "0365_intercepted_call_external",
    "0367_tool_call_script_calls",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
