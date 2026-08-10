"""Clear `channel_tools` out of the specs that briefly carried it.

The capability was offered in the Toolbox for one commit before it moved to the
binding, where it belongs - a bot serves one agent and each binding grants its
own lookups, so a single switch on the spec had one answer for every bot. Any
agent switched on during that window has a binding in its stored spec that now:

- fails publish, because validation refuses a capability nobody chooses on an
  agent, and the message names a switch the Builder no longer shows;
- renders in the Visual map as `channel_tools (missing)`, because the catalog
  no longer lists it;
- does nothing at run time either way, because the run assembles its own binding
  from the exposure.

So it is removed rather than tolerated. Both columns: the draft somebody is
editing and the frozen versions, because a version is what a run resolves and
one refusing to be re-published is the same dead end a step later.

`jsonb` on the way through and back, because `agents.draft_spec` and
`agent_versions.spec` are `json` - which has no `-` operator and no equality
either. The filter is what keeps this a no-op for every other row.

Revision ID: 0021_drop_channel_tools_bindings
Revises: 0020_embed_context_variables
Create Date: 2026-08-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021_drop_channel_tools_bindings"
down_revision: str | Sequence[str] | None = "0020_embed_context_variables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STRIP = """
    UPDATE {table} SET {column} = jsonb_set(
        {column}::jsonb,
        '{{capabilities}}',
        COALESCE(
            (
                SELECT jsonb_agg(binding)
                FROM jsonb_array_elements({column}::jsonb -> 'capabilities') AS binding
                WHERE binding ->> 'id' <> 'channel_tools'
            ),
            '[]'::jsonb
        )
    )::json
    WHERE {column}::jsonb -> 'capabilities' @> '[{{"id": "channel_tools"}}]'
"""


def upgrade() -> None:
    op.execute(_STRIP.format(table="agents", column="draft_spec"))
    op.execute(_STRIP.format(table="agent_versions", column="spec"))


def downgrade() -> None:
    """Nothing to put back.

    The binding did nothing at run time and made the spec unpublishable, so
    restoring it would restore only the dead end. A downgrade that cannot undo
    something says so rather than pretending.
    """
