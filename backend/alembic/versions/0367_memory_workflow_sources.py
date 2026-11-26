"""Bind automation evidence to existing workflow deliveries and mailbox grants."""

import sqlalchemy as sa

from alembic import op

revision: str = "0367_memory_workflow_sources"
down_revision: str = "0366_memory_source_agreement"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    deliveries = "workflow_webhook_deliveries"
    events = "memory_mail_events"
    op.add_column(deliveries, sa.Column("portal_grant_id", sa.Uuid()))
    op.add_column(deliveries, sa.Column("portal_authorization_generation", sa.Uuid()))
    op.create_index("ix_workflow_webhook_delivery_workflow_run", deliveries, ["workflow_run_id"])
    op.drop_constraint("memory_mail_events_organization_id_fkey", events, type_="foreignkey")
    op.create_foreign_key(
        "memory_mail_events_organization_id_fkey",
        events,
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column(events, "quote", type_=sa.String(300), existing_type=sa.String(64))
    op.add_column(
        events, sa.Column("provider", sa.String(16), nullable=False, server_default="gmail")
    )
    op.add_column(events, sa.Column("workflow_delivery_id", sa.Uuid()))
    op.create_foreign_key(
        "memory_mail_events_workflow_delivery_id_fkey",
        events,
        deliveries,
        ["workflow_delivery_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("memory_mail_events_workflow_delivery_id_idx", events, ["workflow_delivery_id"])


def downgrade() -> None:
    deliveries = "workflow_webhook_deliveries"
    events = "memory_mail_events"
    # Older code cannot verify workflow proof. Remove its dependent claims and
    # preserve independent publications, as when a source is disconnected.
    op.execute("DELETE FROM memory_mail_events WHERE workflow_delivery_id IS NOT NULL")
    op.drop_index("memory_mail_events_workflow_delivery_id_idx", table_name=events)
    op.drop_constraint("memory_mail_events_workflow_delivery_id_fkey", events, type_="foreignkey")
    op.drop_column(events, "workflow_delivery_id")
    op.drop_column(events, "provider")
    op.alter_column(events, "quote", type_=sa.String(64), existing_type=sa.String(300))
    op.drop_constraint("memory_mail_events_organization_id_fkey", events, type_="foreignkey")
    op.create_foreign_key(
        "memory_mail_events_organization_id_fkey",
        events,
        "memory_mail_sources",
        ["organization_id"],
        ["organization_id"],
        ondelete="CASCADE",
    )
    op.drop_index("ix_workflow_webhook_delivery_workflow_run", table_name=deliveries)
    op.drop_column(deliveries, "portal_authorization_generation")
    op.drop_column(deliveries, "portal_grant_id")
