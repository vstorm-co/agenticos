"""What one run handed its model, kept beside the run rather than on it.

A run row says what an agent cost and how it ended; a transcript says what was
asked and what came back. Neither says what the model was actually given - the
instructions as composed, the tools as described, the settings as sent - and
that is not derivable afterwards: the prompt is the spec's instructions plus the
platform's, plus a channel binding's, plus the bound skills, plus whatever
reminder fired, and the tool schemas come from the registry, the organization's
MCP servers and whatever tool search revealed. Reconstructing it from the stored
spec would be a second implementation of the builder, and a second
implementation disagrees.

So it is recorded from the wire (`app/agents/manifest.py`) and stored here, one
row per run, written when the run ends and read only by the run detail.

A table of its own rather than a column on `agent_runs`, because that table is
the most-listed in the product - run history, the spend tab, the dashboard
figures, the CSV export - and a JSONB document holding every tool's JSON schema
would be read by all of them to answer a question none of them asks.

Revision ID: 0038_run_manifest
Revises: 0037_deployment_settings
Create Date: 2026-08-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0038_run_manifest"
down_revision: str | None = "0037_deployment_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run_manifests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("run_manifests_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("run_manifests_run_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("run_manifests_pkey")),
    )
    op.create_index(
        op.f("run_manifests_organization_id_idx"),
        "run_manifests",
        ["organization_id"],
        unique=False,
    )
    op.create_index(op.f("run_manifests_run_id_idx"), "run_manifests", ["run_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("run_manifests_run_id_idx"), table_name="run_manifests")
    op.drop_index(op.f("run_manifests_organization_id_idx"), table_name="run_manifests")
    op.drop_table("run_manifests")
