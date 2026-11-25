"""A `run_code` call keeps every call its script made.

Code mode folds an agent's tools into one `run_code` script, and the transcript
held only that script. An eval scored a code-mode agent's trajectory without the
tools it called, and a recording of its run had nothing to answer them with.
Each script's calls are now kept on the `run_code` row, as JSON beside its
result, rather than as rows of their own that every reader of a turn's calls
would have to skip.

Downgrade drops the column, and with it what scripts called: the older code
neither reads it nor records it anywhere else.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0367_tool_call_script_calls"
down_revision: str | None = "0366_improvement_holdout_share"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tool_calls",
        sa.Column("script_calls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tool_calls", "script_calls")
