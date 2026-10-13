"""System agents and the AI assistance switch, the base eval scoring runs on.

`agents.system_key` marks an agent the platform seeded and starts itself - the
eval judge first, the case generator and the authoring assistant after it. A key
rather than a reserved slug, because the slug derives from a name the organization
may change, and a person's own agent may already hold it. The partial unique index
gives each organization at most one agent per key; ordinary agents leave it null.
No existing agent becomes a system agent: one is seeded the first time something
needs it.

`organizations.ai_assistance_enabled` is the one switch for every model-backed
eval and authoring feature. On by default, because an organization that has
changed nothing should get the features the release adds; one that does not want
models judging or drafting turns it off, and the services refuse from then on.

Nothing existing changes meaning, so the downgrade drops what was added and loses
only which agents were seeded and whether an organization had switched AI
assistance off.

Revision ID: 0108_eval_scoring
Revises: 0106_datasets
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0108_eval_scoring"
down_revision: str | None = "0106_datasets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "ai_assistance_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column("agents", sa.Column("system_key", sa.String(length=64), nullable=True))
    op.create_index(
        "uq_agents_org_system_key",
        "agents",
        ["organization_id", "system_key"],
        unique=True,
        postgresql_where=sa.text("system_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_agents_org_system_key", table_name="agents")
    op.drop_column("agents", "system_key")
    op.drop_column("organizations", "ai_assistance_enabled")
