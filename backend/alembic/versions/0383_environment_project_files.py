"""Keep an owned desktop's Project path independent of its real agent run.

Existing leases remain run-owned with their original short expiry. Environment
leases are separately revocable and reauthorize the live environment per RPC;
no run is created or kept running for a manual desktop.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0383_environment_project_files"
down_revision: str = "0382_merge_live_environments"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.alter_column("project_filesystem_leases", "run_id", nullable=True)
    op.add_column(
        "project_filesystem_leases",
        sa.Column("environment_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_project_filesystem_environment",
        "project_filesystem_leases",
        "conversation_environments",
        ["environment_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "project_filesystem_leases_environment_id_idx",
        "project_filesystem_leases",
        ["environment_id"],
    )
    op.create_check_constraint(
        op.f("ck_project_filesystem_lease_owner"),
        "project_filesystem_leases",
        "(run_id IS NOT NULL AND environment_id IS NULL) OR "
        "(run_id IS NULL AND environment_id IS NOT NULL)",
    )


def downgrade() -> None:
    live_desktop = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM conversation_environments "
            "WHERE kind='desktop' AND resource_ciphertext IS NOT NULL)"
        )
    )
    if live_desktop:
        raise RuntimeError(
            "End retained desktop environments and drain their cleanup jobs before downgrading "
            "environment Project files; older workers cannot decode the new sealed handles."
        )
    # An older gateway cannot authorize environment-owned paths. Revoke them
    # rather than converting them into fabricated or revived run authority.
    op.execute(sa.text("DELETE FROM project_filesystem_leases WHERE environment_id IS NOT NULL"))
    op.drop_constraint(
        op.f("ck_project_filesystem_lease_owner"), "project_filesystem_leases", type_="check"
    )
    op.drop_index(
        "project_filesystem_leases_environment_id_idx", table_name="project_filesystem_leases"
    )
    op.drop_constraint(
        "fk_project_filesystem_environment", "project_filesystem_leases", type_="foreignkey"
    )
    op.drop_column("project_filesystem_leases", "environment_id")
    op.alter_column("project_filesystem_leases", "run_id", nullable=False)
