"""Independent trigger entries and one exposure per trigger kind.

Revision ID: 0242_workflow_entry_triggers
Revises: 0241_attempt_reservations
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0242_workflow_entry_triggers"
down_revision: str | Sequence[str] | None = "0241_attempt_reservations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflows",
        sa.Column(
            "live_triggers",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.execute(
        "UPDATE workflows SET live_triggers = jsonb_build_array(live_trigger) WHERE live_trigger IS NOT NULL"
    )
    op.add_column(
        "workflow_runs", sa.Column("entry_node_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.drop_constraint("uq_workflow_exposure_workflow", "workflow_exposures", type_="unique")
    op.create_unique_constraint(
        "uq_workflow_exposure_workflow_adapter", "workflow_exposures", ["workflow_id", "adapter"]
    )


def downgrade() -> None:
    # Refuse before dropping anything: retaining all registered triggers takes priority.
    duplicate = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT id FROM workflows WHERE jsonb_array_length(live_triggers) > 1 "
                "UNION ALL SELECT workflow_id FROM workflow_exposures "
                "GROUP BY workflow_id HAVING count(*) > 1 "
                "UNION ALL SELECT id FROM workflow_versions WHERE ("
                "SELECT count(*) FROM jsonb_array_elements(graph->'nodes') AS node "
                "WHERE node->>'id' = graph->>'entry_node_id' "
                "OR node->>'definition_id' LIKE 'trigger.%' "
                "OR node->>'definition_id' = 'core.input') > 1 LIMIT 1"
            )
        )
        .first()
    )
    if duplicate is not None:
        raise RuntimeError("Remove workflows with multiple trigger entries before downgrading")
    op.drop_constraint(
        "uq_workflow_exposure_workflow_adapter", "workflow_exposures", type_="unique"
    )
    op.create_unique_constraint(
        "uq_workflow_exposure_workflow", "workflow_exposures", ["workflow_id"]
    )
    op.drop_column("workflow_runs", "entry_node_id")
    op.drop_column("workflows", "live_triggers")
