"""Remove the `memory_mem0` binding from every stored agent spec (#2090).

Native memory replaces mem0. Refuse to remove endpoint and credential mappings
while a legacy binding remains: the operator must inventory the external stores,
verify their purge, then explicitly remove the bindings before retrying. A clean
installation has nothing to migrate. This revision has not shipped on main.

No remote request is made by Alembic, and downgrade restores nothing.

Revision ID: 0248_drop_memory_mem0
Revises: 0247_merge_deployment_workflows
Create Date: 2026-11-01
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0248_drop_memory_mem0"
down_revision: str | None = "0247_merge_deployment_workflows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_BINDINGS = """
SELECT 1 FROM agents
WHERE draft_spec -> 'capabilities' @> '[{"id": "memory_mem0"}]'::jsonb
UNION ALL
SELECT 1 FROM agent_versions
WHERE spec -> 'capabilities' @> '[{"id": "memory_mem0"}]'::jsonb
LIMIT 1
"""


def upgrade() -> None:
    if op.get_bind().execute(text(_LEGACY_BINDINGS)).first() is not None:
        raise RuntimeError(
            "Legacy mem0 bindings remain. Upgrade stopped without removing erasure metadata. "
            "Back up the database and vault keys; inventory the endpoints and credential mappings; "
            "verify external memory erasure; then explicitly remove memory_mem0 bindings from "
            "agents.draft_spec and agent_versions.spec before retrying. "
            "See docs/deploy.md#native-memory-upgrade."
        )


def downgrade() -> None:
    pass
