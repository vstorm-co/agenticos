"""Keep evaluation pipeline configuration with its dataset.

Revision ID: 0252_dataset_helpers
Revises: 0251_merge_improvement_discord
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0252_dataset_helpers"
down_revision: str = "0251_merge_improvement_discord"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "datasets",
        sa.Column("helper_settings", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    # Preserve a dataset's chosen grader before its user-agent controls disappear.
    op.execute(
        """
        UPDATE datasets AS dataset
        SET scoring = jsonb_set(
            dataset.scoring, '{judge}',
            COALESCE(dataset.scoring->'judge', '{}'::jsonb) || jsonb_build_object(
                'model_profile_id', version.spec->'model_profile_id',
                'instructions', version.spec->'instructions'
            )
        )
        FROM agents AS agent
        JOIN agent_versions AS version ON version.id = agent.current_version_id
        WHERE (dataset.scoring->'judge'->>'agent_id' = agent.id::text
            OR (dataset.scoring->'judge'->>'agent_id' IS NULL AND agent.system_key = 'eval_judge'))
          AND agent.organization_id = dataset.organization_id
        """
    )


def downgrade() -> None:
    op.drop_column("datasets", "helper_settings")
