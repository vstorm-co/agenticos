"""Freeze each background pipeline's selected model and instructions.

Revision ID: 0253_helper_snapshots
Revises: 0252_dataset_helpers
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0253_helper_snapshots"
down_revision: str = "0252_dataset_helpers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PIPELINES = (
    ("case_generations", "generator_agent_id", "case_generator"),
    ("improvement_runs", "improver_agent_id", "authoring_improver"),
    ("authoring_requests", "improver_agent_id", "authoring_improver"),
)


def upgrade() -> None:
    for table, identity, key in _PIPELINES:
        op.add_column(
            table,
            sa.Column("helper_settings", postgresql.JSONB(), nullable=False, server_default="{}"),
        )
        # Identifiers and keys are the fixed declarations above, never request input.
        op.execute(
            f"""
            UPDATE {table} AS task
            SET helper_settings = jsonb_build_object(
                'model_profile_id', version.spec->'model_profile_id',
                'instructions', version.spec->'instructions'
            )
            FROM agents AS agent
            JOIN agent_versions AS version ON version.id = agent.current_version_id
            WHERE agent.organization_id = task.organization_id
              AND (task.{identity} = agent.id OR
                   (task.{identity} IS NULL AND agent.system_key = '{key}'))
            """
        )


def downgrade() -> None:
    for table, _, _ in reversed(_PIPELINES):
        op.drop_column(table, "helper_settings")
