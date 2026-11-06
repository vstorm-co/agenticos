"""Serialize queued watches and nightly work sharing one member's budget.

Stop API/sweep producers and drain workers before upgrading. Already-running
unkeyed model work cannot be made retroactively exclusive without cancelling it.
Queued legacy jobs receive the same key as newly enqueued work.

Revision ID: 0285_member_proactivity
Revises: 0284_shipped_agent_defaults
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0285_member_proactivity"
down_revision: str | None = "0284_shipped_agent_defaults"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE = """
SELECT 1 FROM background_jobs
WHERE status = 'running' AND kind IN ('think-for-person', 'look-through-watch') LIMIT 1
"""
_NIGHTLY = """
UPDATE background_jobs SET concurrency_key =
    'proactivity:' || organization_id::text || ':' || (payload ->> 'user_id')
WHERE status = 'queued' AND kind = 'think-for-person'
  AND organization_id IS NOT NULL AND payload ->> 'user_id' IS NOT NULL
"""
_WATCHES = """
UPDATE background_jobs AS job SET concurrency_key =
    'proactivity:' || watch.organization_id::text || ':' || watch.user_id::text
FROM watches AS watch
WHERE job.status = 'queued' AND job.kind = 'look-through-watch'
  AND job.organization_id = watch.organization_id
  AND job.payload ->> 'watch_id' = watch.id::text
"""


def _drained() -> None:
    if op.get_bind().execute(text(_ACTIVE)).first() is not None:
        raise RuntimeError(
            "Drain proactive workers and stop API/sweep producers before this migration"
        )


def upgrade() -> None:
    _drained()
    op.execute(_NIGHTLY)
    op.execute(_WATCHES)


def downgrade() -> None:
    _drained()
    op.execute("""
        UPDATE background_jobs SET concurrency_key = NULL
        WHERE kind IN ('think-for-person', 'look-through-watch')
          AND concurrency_key LIKE 'proactivity:%'
    """)
