"""Per-organization retention, its deployment-wide bounds, and spend that outlives a run.

Nothing was deleted on a schedule before this: conversations, run rows and
manifests, workspaces, agent memory, uploaded documents and audit entries lived
until somebody deleted the organization. Two standards pull opposite ways and
both need a setting, so the period is per class and the layers are explicit
(#1420).

Three columns carry the policy. `organizations.retention_days` is what an
organization asked for, per class; `deployment_settings.retention_defaults` is
what one that asked for nothing gets; `deployment_settings.retention_max_days`
is the ceiling it cannot raise. All three are nullable mappings with holes,
because "unset" and "keep for ever" are different answers and six columns of
integers could not tell them apart.

`audit_retention_floor_days` runs the other way: the deployment sets the
*shortest* an audit entry may live and an organization may only lengthen it. Null
takes the built-in six years, which is HIPAA §164.316(b)(2).

`purged_run_spend` is the one thing that survives a purge. A month's bill is a sum
over `agent_runs`, so hard-deleting them would drop an organization's
month-to-date spend to zero mid-month and stop its budget cap enforcing. The row
holds a total and a count for one month and no content at all.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "0082_retention_policies"
down_revision: str | Sequence[str] | None = "0080_audit_checkpoints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("retention_days", JSONB(), nullable=True))
    op.add_column("deployment_settings", sa.Column("retention_defaults", JSONB(), nullable=True))
    op.add_column("deployment_settings", sa.Column("retention_max_days", JSONB(), nullable=True))
    op.add_column(
        "deployment_settings",
        sa.Column("audit_retention_floor_days", sa.Integer(), nullable=True),
    )

    op.create_table(
        "purged_run_spend",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("run_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "period_start", name="purged_run_spend_period_key"),
    )
    op.create_index("purged_run_spend_organization_id_idx", "purged_run_spend", ["organization_id"])


def downgrade() -> None:
    op.drop_index("purged_run_spend_organization_id_idx", table_name="purged_run_spend")
    op.drop_table("purged_run_spend")
    op.drop_column("deployment_settings", "audit_retention_floor_days")
    op.drop_column("deployment_settings", "retention_max_days")
    op.drop_column("deployment_settings", "retention_defaults")
    op.drop_column("organizations", "retention_days")
