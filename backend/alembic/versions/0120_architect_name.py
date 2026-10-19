"""Call an existing organization's assistant the Architect (#2075).

The assistant was installed as "AI Architect", or "AI Architect (AgenticOS)"
where an agent already held that handle. The template is named Architect now,
and the console names the assistant in the reader's language only while it keeps
a name it was installed with - so an assistant installed before the rename read
as one an administrator had renamed. Only the two installed names move; a name
somebody chose is left alone. The handle stays: it is frozen at creation, and a
mention or an API caller may already use it. Published versions keep the name
they were published under, being the record of what ran.

Revision ID: 0120_architect_name
Revises: 0119_mcp_server_alerts
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0120_architect_name"
down_revision: str | None = "0119_mcp_server_alerts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RENAMES = (
    ("AI Architect", "Architect"),
    ("AI Architect (AgenticOS)", "Architect (AgenticOS)"),
)

_RENAME = sa.text(
    """
    UPDATE agents
    SET name = :new,
        draft_spec = jsonb_set(draft_spec, '{name}', to_jsonb(CAST(:new AS text)))
    WHERE name = :old
      AND id IN (SELECT agent_id FROM organization_assistants)
    """
)


def upgrade() -> None:
    for old, new in _RENAMES:
        op.get_bind().execute(_RENAME, {"old": old, "new": new})


def downgrade() -> None:
    for old, new in _RENAMES:
        op.get_bind().execute(_RENAME, {"old": new, "new": old})
