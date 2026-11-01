"""Remove the `memory_mem0` binding from every stored agent spec (#2090).

mem0 is gone: native memory is the one mechanism. A spec that still names the
capability would fail to load, including published versions that pinned
environments run, so the binding is dropped from drafts and from every version.
Nothing else in a spec changes, and no note is touched: what mem0 held lives in
somebody else's service, which this platform neither reads nor deletes.

The downgrade cannot restore the binding (its secret and URL are not kept), so it
is a no-op.

Revision ID: 0248_drop_memory_mem0
Revises: 0247_merge_deployment_workflows
Create Date: 2026-11-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0248_drop_memory_mem0"
down_revision: str | None = "0247_merge_deployment_workflows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STRIP = """
UPDATE {table}
SET {column} = jsonb_set(
    {column},
    '{{capabilities}}',
    COALESCE(
        (
            SELECT jsonb_agg(binding)
            FROM jsonb_array_elements({column} -> 'capabilities') AS binding
            WHERE binding ->> 'id' IS DISTINCT FROM 'memory_mem0'
        ),
        '[]'::jsonb
    )
)
WHERE jsonb_typeof({column} -> 'capabilities') = 'array'
  AND {column} -> 'capabilities' @> '[{{"id": "memory_mem0"}}]'::jsonb
"""


def upgrade() -> None:
    op.execute(_STRIP.format(table="agents", column="draft_spec"))
    op.execute(_STRIP.format(table="agent_versions", column="spec"))


def downgrade() -> None:
    pass
