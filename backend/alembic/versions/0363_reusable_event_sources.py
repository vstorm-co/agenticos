"""Reusable webhook ingress for routines and workflows.

Sources keep organization-bound credentials separate from exported workflow
configuration. Accepted deliveries and each subscription's dispatch commit in
one transaction; tenant-composite foreign keys prevent cross-organization
attachments. Existing dedicated ingress and literal prompts retain their shape.
A waiting routine keeps its source identity so resuming rechecks the same source.

Downgrade requires detaching sources and settling pending source work.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0363_reusable_event_sources"
down_revision: str = "0362_merge_native_release"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_agent_trigger_tenant", "agent_triggers", ["id", "organization_id"]
    )
    op.create_unique_constraint(
        "uq_workflow_exposure_tenant", "workflow_exposures", ["id", "organization_id"]
    )
    op.create_table(
        "event_source_credentials",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("sealed_secret", sa.Text(), nullable=False),
        sa.Column("secret_key_version", sa.Integer(), nullable=False),
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
            name=op.f("event_source_credentials_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("event_source_credentials_pkey")),
        sa.UniqueConstraint("id", "organization_id", name="uq_event_source_credential_tenant"),
    )
    op.create_index(
        op.f("event_source_credentials_organization_id_idx"),
        "event_source_credentials",
        ["organization_id"],
        unique=False,
    )
    op.create_table(
        "event_sources",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("auth", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("delivery_id_header", sa.String(length=128), nullable=True),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("secret_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "provider IN ('github', 'linear', 'hubspot', 'zendesk', 'webhook')",
            name=op.f("event_sources_ck_event_source_provider_check"),
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'org')",
            name=op.f("event_sources_ck_event_source_visibility_check"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("event_sources_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("event_sources_owner_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["secret_id", "organization_id"],
            ["event_source_credentials.id", "event_source_credentials.organization_id"],
            name="fk_event_source_credential_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("event_sources_pkey")),
        sa.UniqueConstraint("id", "organization_id", name="uq_event_source_tenant"),
        sa.UniqueConstraint("secret_id", name=op.f("event_sources_secret_id_key")),
    )
    op.create_index(
        op.f("event_sources_organization_id_idx"),
        "event_sources",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("event_sources_owner_user_id_idx"), "event_sources", ["owner_user_id"], unique=False
    )
    op.create_table(
        "event_deliveries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("headers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            name=op.f("event_deliveries_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["event_sources.id", "event_sources.organization_id"],
            name="fk_event_delivery_source_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("event_deliveries_pkey")),
        sa.UniqueConstraint("id", "organization_id", name="uq_event_delivery_tenant"),
        sa.UniqueConstraint("source_id", "external_id", name="uq_event_delivery_source_external"),
    )
    op.create_index(
        op.f("event_deliveries_organization_id_idx"),
        "event_deliveries",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("event_deliveries_source_id_idx"), "event_deliveries", ["source_id"], unique=False
    )
    op.create_table(
        "event_subscriptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("trigger_id", sa.UUID(), nullable=True),
        sa.Column("exposure_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(trigger_id IS NULL) <> (exposure_id IS NULL)",
            name=op.f("event_subscriptions_ck_event_subscription_target_check"),
        ),
        sa.ForeignKeyConstraint(
            ["exposure_id", "organization_id"],
            ["workflow_exposures.id", "workflow_exposures.organization_id"],
            name="fk_event_subscription_exposure_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("event_subscriptions_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["event_sources.id", "event_sources.organization_id"],
            name="fk_event_subscription_source_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["trigger_id", "organization_id"],
            ["agent_triggers.id", "agent_triggers.organization_id"],
            name="fk_event_subscription_trigger_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("event_subscriptions_pkey")),
        sa.UniqueConstraint("exposure_id", name=op.f("event_subscriptions_exposure_id_key")),
        sa.UniqueConstraint("id", "organization_id", name="uq_event_subscription_tenant"),
        sa.UniqueConstraint("trigger_id", name=op.f("event_subscriptions_trigger_id_key")),
    )
    op.create_index(
        op.f("event_subscriptions_organization_id_idx"),
        "event_subscriptions",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("event_subscriptions_source_id_idx"),
        "event_subscriptions",
        ["source_id"],
        unique=False,
    )
    op.create_table(
        "event_dispatches",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("delivery_id", sa.UUID(), nullable=False),
        sa.Column("subscription_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workflow_version_id", sa.UUID(), nullable=True),
        sa.Column("routine_source_policy_id", sa.UUID(), nullable=True),
        sa.Column("workflow_principal_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'admitted', 'skipped', 'failed')",
            name=op.f("event_dispatches_ck_event_dispatch_status_check"),
        ),
        sa.ForeignKeyConstraint(
            ["delivery_id", "organization_id"],
            ["event_deliveries.id", "event_deliveries.organization_id"],
            name="fk_event_dispatch_delivery_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("event_dispatches_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id", "organization_id"],
            ["event_subscriptions.id", "event_subscriptions.organization_id"],
            name="fk_event_dispatch_subscription_tenant",
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["event_subscriptions.id"],
            name=op.f("event_dispatches_subscription_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("event_dispatches_pkey")),
        sa.UniqueConstraint("delivery_id", "subscription_id", name="uq_event_dispatch_target"),
    )
    op.create_index(
        op.f("event_dispatches_delivery_id_idx"), "event_dispatches", ["delivery_id"], unique=False
    )
    op.create_index(
        op.f("event_dispatches_organization_id_idx"),
        "event_dispatches",
        ["organization_id"],
        unique=False,
    )
    op.add_column("agent_triggers", sa.Column("source_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_agent_trigger_source_tenant",
        "agent_triggers",
        "event_sources",
        ["source_id", "organization_id"],
        ["id", "organization_id"],
        ondelete="RESTRICT",
    )
    op.add_column("routine_device_waits", sa.Column("event_source_id", sa.UUID(), nullable=True))
    op.add_column("workflow_exposures", sa.Column("source_id", sa.UUID(), nullable=True))
    op.create_index(
        op.f("workflow_exposures_source_id_idx"), "workflow_exposures", ["source_id"], unique=False
    )
    op.create_foreign_key(
        "fk_workflow_exposure_source_tenant",
        "workflow_exposures",
        "event_sources",
        ["source_id", "organization_id"],
        ["id", "organization_id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint(
        op.f("agent_triggers_ck_trigger_shape_check"), "agent_triggers", type_="check"
    )
    op.create_check_constraint(
        op.f("agent_triggers_ck_trigger_shape_check"),
        "agent_triggers",
        "(trigger_type = 'schedule' AND (next_fire_at IS NOT NULL OR one_shot) AND event_source IS NULL AND source_id IS NULL AND ((schedule_kind = 'interval' AND interval_seconds IS NOT NULL AND cron_expression IS NULL) OR (schedule_kind = 'cron' AND cron_expression IS NOT NULL AND interval_seconds IS NULL))) OR (trigger_type = 'event' AND event_source IS NOT NULL AND ((source_id IS NULL AND event_source IN ('gmail', 'google_calendar', 'google_drive', 'microsoft_files', 'outlook', 'outlook_calendar') AND event_secret_encrypted IS NULL AND secret_key_version IS NULL) OR (source_id IS NULL AND event_source NOT IN ('gmail', 'google_calendar', 'google_drive', 'microsoft_files', 'outlook', 'outlook_calendar') AND event_secret_encrypted IS NOT NULL AND secret_key_version IS NOT NULL) OR (source_id IS NOT NULL AND event_source IN ('webhook', 'github', 'linear', 'hubspot', 'zendesk') AND event_secret_encrypted IS NULL AND secret_key_version IS NULL)) AND next_fire_at IS NULL AND interval_seconds IS NULL AND cron_expression IS NULL)",
    )
    op.drop_constraint(
        op.f("workflow_exposures_ck_workflow_exposure_shape_check"),
        "workflow_exposures",
        type_="check",
    )
    op.create_check_constraint(
        op.f("workflow_exposures_ck_workflow_exposure_shape_check"),
        "workflow_exposures",
        "(adapter IN ('webhook', 'github') AND ((source_id IS NULL AND secret_encrypted IS NOT NULL AND secret_key_version IS NOT NULL) OR (adapter = 'webhook' AND source_id IS NOT NULL AND secret_encrypted IS NULL AND secret_key_version IS NULL)) AND schedule_kind IS NULL AND interval_seconds IS NULL AND cron_expression IS NULL AND next_fire_at IS NULL AND form_token IS NULL AND channel_bot_id IS NULL) OR (adapter = 'schedule' AND secret_encrypted IS NULL AND secret_key_version IS NULL AND next_fire_at IS NOT NULL AND form_token IS NULL AND channel_bot_id IS NULL AND ((schedule_kind = 'interval' AND interval_seconds IS NOT NULL AND cron_expression IS NULL) OR (schedule_kind = 'cron' AND cron_expression IS NOT NULL AND interval_seconds IS NULL))) OR (adapter = 'form' AND form_token IS NOT NULL AND channel_bot_id IS NULL AND secret_encrypted IS NULL AND secret_key_version IS NULL AND schedule_kind IS NULL AND interval_seconds IS NULL AND cron_expression IS NULL AND next_fire_at IS NULL) OR (adapter IN ('channel', 'gmail', 'outlook') AND form_token IS NULL AND secret_encrypted IS NULL AND secret_key_version IS NULL AND schedule_kind IS NULL AND interval_seconds IS NULL AND cron_expression IS NULL AND next_fire_at IS NULL AND (adapter = 'channel' OR channel_bot_id IS NULL))",
    )
    op.create_check_constraint(
        op.f("workflow_exposures_ck_workflow_exposure_source_check"),
        "workflow_exposures",
        "source_id IS NULL OR adapter = 'webhook'",
    )


def downgrade() -> None:
    # Keep admissions, claims and scheduler ticks from changing what is safe
    # to retire between the checks below and the transactional schema change.
    op.execute(
        "LOCK TABLE agent_triggers, workflow_exposures, routine_device_waits, event_dispatches "
        "IN ACCESS EXCLUSIVE MODE"
    )
    op.execute("LOCK TABLE background_schedules, background_jobs IN SHARE ROW EXCLUSIVE MODE")
    outstanding = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM agent_triggers WHERE source_id IS NOT NULL) "
            "OR EXISTS(SELECT 1 FROM workflow_exposures WHERE source_id IS NOT NULL) "
            "OR EXISTS(SELECT 1 FROM routine_device_waits WHERE status = 'waiting' AND event_source_id IS NOT NULL) "
            "OR EXISTS(SELECT 1 FROM event_dispatches WHERE status = 'pending')"
        )
    )
    if outstanding:
        raise RuntimeError("Detach event sources and settle pending source work before downgrade")
    retired_kinds = "('dispatch-source-event', 'source-delivery-retention')"
    if op.get_bind().scalar(
        sa.text(
            f"SELECT EXISTS (SELECT 1 FROM background_jobs WHERE kind IN {retired_kinds} "
            "AND status = 'running')"
        )
    ):
        raise RuntimeError("Wait for running event source jobs to finish before downgrade")
    # Dead fires can be retried from the queue. Do not discard their input, or
    # that of a queued/running fire, to make it fit the previous worker schema.
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM background_jobs WHERE kind = 'fire-trigger' "
            "AND status IN ('queued', 'running', 'dead') "
            "AND payload->>'event_source_id' IS NOT NULL)"
        )
    ):
        raise RuntimeError(
            "Drain or cancel source-bound fire-trigger jobs, including retryable dead jobs, before downgrade"
        )
    # A dedicated or scheduled fire may have serialized event_source_id as
    # JSON null. The old worker rejects unknown fields, null or not.
    op.execute(
        "UPDATE background_jobs SET payload = payload - 'event_source_id' "
        "WHERE kind = 'fire-trigger' AND status IN ('queued', 'running', 'dead') "
        "AND payload ? 'event_source_id' "
        "AND payload->>'event_source_id' IS NULL"
    )
    # No pending dispatch remains. Any queued or retryable job of these
    # retired kinds would only find a deleted/settled dispatch or sweep tables
    # that no longer exist. Keep its history without giving it to the old worker.
    op.execute(
        "UPDATE background_jobs SET status = 'cancelled', finished_at = coalesce(finished_at, now()), "
        "settled_at = now(), last_error = coalesce(last_error, 'Event source job retired on downgrade') "
        f"WHERE kind IN {retired_kinds} AND status IN ('queued', 'dead')"
    )
    op.execute("DELETE FROM background_schedules WHERE name = 'source-delivery-retention'")
    op.execute(f"DELETE FROM background_task_kinds WHERE kind IN {retired_kinds}")
    op.drop_constraint(
        op.f("agent_triggers_ck_trigger_shape_check"), "agent_triggers", type_="check"
    )
    op.create_check_constraint(
        op.f("agent_triggers_ck_trigger_shape_check"),
        "agent_triggers",
        "(trigger_type = 'schedule' AND (next_fire_at IS NOT NULL OR one_shot) AND event_source IS NULL AND ((schedule_kind = 'interval' AND interval_seconds IS NOT NULL AND cron_expression IS NULL) OR (schedule_kind = 'cron' AND cron_expression IS NOT NULL AND interval_seconds IS NULL))) OR (trigger_type = 'event' AND event_source IS NOT NULL AND ((event_source IN ('gmail', 'google_calendar', 'google_drive', 'microsoft_files', 'outlook', 'outlook_calendar') AND event_secret_encrypted IS NULL AND secret_key_version IS NULL) OR (event_source NOT IN ('gmail', 'google_calendar', 'google_drive', 'microsoft_files', 'outlook', 'outlook_calendar') AND event_secret_encrypted IS NOT NULL AND secret_key_version IS NOT NULL)) AND next_fire_at IS NULL AND interval_seconds IS NULL AND cron_expression IS NULL)",
    )
    op.drop_constraint(
        op.f("workflow_exposures_ck_workflow_exposure_shape_check"),
        "workflow_exposures",
        type_="check",
    )
    op.create_check_constraint(
        op.f("workflow_exposures_ck_workflow_exposure_shape_check"),
        "workflow_exposures",
        "(adapter IN ('webhook', 'github') AND secret_encrypted IS NOT NULL AND secret_key_version IS NOT NULL AND schedule_kind IS NULL AND interval_seconds IS NULL AND cron_expression IS NULL AND next_fire_at IS NULL AND form_token IS NULL AND channel_bot_id IS NULL) OR (adapter = 'schedule' AND secret_encrypted IS NULL AND secret_key_version IS NULL AND next_fire_at IS NOT NULL AND form_token IS NULL AND channel_bot_id IS NULL AND ((schedule_kind = 'interval' AND interval_seconds IS NOT NULL AND cron_expression IS NULL) OR (schedule_kind = 'cron' AND cron_expression IS NOT NULL AND interval_seconds IS NULL))) OR (adapter = 'form' AND form_token IS NOT NULL AND channel_bot_id IS NULL AND secret_encrypted IS NULL AND secret_key_version IS NULL AND schedule_kind IS NULL AND interval_seconds IS NULL AND cron_expression IS NULL AND next_fire_at IS NULL) OR (adapter IN ('channel', 'gmail', 'outlook') AND form_token IS NULL AND secret_encrypted IS NULL AND secret_key_version IS NULL AND schedule_kind IS NULL AND interval_seconds IS NULL AND cron_expression IS NULL AND next_fire_at IS NULL AND (adapter = 'channel' OR channel_bot_id IS NULL))",
    )
    op.drop_constraint(
        op.f("workflow_exposures_ck_workflow_exposure_source_check"),
        "workflow_exposures",
        type_="check",
    )
    op.drop_constraint(
        "fk_workflow_exposure_source_tenant", "workflow_exposures", type_="foreignkey"
    )
    op.drop_index(op.f("workflow_exposures_source_id_idx"), table_name="workflow_exposures")
    op.drop_column("workflow_exposures", "source_id")
    op.drop_column("routine_device_waits", "event_source_id")
    op.drop_constraint("fk_agent_trigger_source_tenant", "agent_triggers", type_="foreignkey")
    op.drop_column("agent_triggers", "source_id")
    op.drop_index(op.f("event_dispatches_organization_id_idx"), table_name="event_dispatches")
    op.drop_index(op.f("event_dispatches_delivery_id_idx"), table_name="event_dispatches")
    op.drop_table("event_dispatches")
    op.drop_index(op.f("event_subscriptions_source_id_idx"), table_name="event_subscriptions")
    op.drop_index(op.f("event_subscriptions_organization_id_idx"), table_name="event_subscriptions")
    op.drop_table("event_subscriptions")
    op.drop_index(op.f("event_deliveries_source_id_idx"), table_name="event_deliveries")
    op.drop_index(op.f("event_deliveries_organization_id_idx"), table_name="event_deliveries")
    op.drop_table("event_deliveries")
    op.drop_index(op.f("event_sources_owner_user_id_idx"), table_name="event_sources")
    op.drop_index(op.f("event_sources_organization_id_idx"), table_name="event_sources")
    op.drop_table("event_sources")
    op.drop_index(
        op.f("event_source_credentials_organization_id_idx"), table_name="event_source_credentials"
    )
    op.drop_table("event_source_credentials")
    op.drop_constraint("uq_agent_trigger_tenant", "agent_triggers", type_="unique")
    op.drop_constraint("uq_workflow_exposure_tenant", "workflow_exposures", type_="unique")
