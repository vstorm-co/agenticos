"""Add reversible memory aliases, backfill checkpoints and Inbox rules."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0369_memory_inbox_and_objects"
down_revision: str = "0368_memory_note_revisions"
branch_labels: None = None
depends_on: None = None


_EVENT_TYPE_MIGRATIONS = (
    ("notifications", "ck_notifications_event_type"),
    ("notification_preferences", "ck_notification_preferences_event_type"),
)
_EVENT_TYPES = (
    "event_type IN ("
    "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
    "'ingestion_completed', 'ingestion_failed', 'usage_report', "
    "'agent_usage_report', 'security_event', 'configuration_changed', "
    "'announcement', 'artifact_version_published', 'resource_shared', "
    "'budget_warning', 'mcp_server_down', 'mcp_server_recovered', "
    "'background_task_paused', 'eval_suite_failed', 'promotion_overridden', "
    "'shared_change_applied', 'workflow_notification', "
    "'artifact_owner_changed', 'artifact_share_requested', "
    "'capability_requested', 'suggestion', 'finding', 'improvement_finished', "
    "'eval_suite_reevaluated', 'eval_run_finished', 'case_generation_finished', "
    "'workflow_log_alert', 'memory_deadline_change')"
)


def _replace_checks(*, add_memory: bool) -> None:
    expression = (
        _EVENT_TYPES if add_memory else _EVENT_TYPES.replace(", 'memory_deadline_change'", "")
    )
    for table, name in _EVENT_TYPE_MIGRATIONS:
        if not add_memory:
            op.execute(sa.text(f"DELETE FROM {table} WHERE event_type = 'memory_deadline_change'"))
        op.drop_constraint(name, table, type_="check")
        # The old, stricter constraint proves every retained row valid. Avoid
        # scanning Inbox history while holding the replace operation's lock.
        op.create_check_constraint(name, table, expression, postgresql_not_valid=True)


def _backfill_index(*, create: bool) -> None:
    # Build the legacy scan index online. Drop a possibly invalid index left
    # by an interrupted concurrent build before trying it again.
    name = "ix_memory_claims_object_backfill"
    table = "memory_claims"
    if op.get_context().as_sql:
        if create:
            op.create_index(
                name,
                table,
                ["organization_id", "created_at", "id"],
                postgresql_where=sa.text("object_id IS NULL"),
            )
        else:
            op.drop_index(name, table_name=table)
        return
    with op.get_context().autocommit_block():
        op.drop_index(name, table_name=table, if_exists=True, postgresql_concurrently=True)
        if create:
            op.create_index(
                name,
                table,
                ["organization_id", "created_at", "id"],
                postgresql_where=sa.text("object_id IS NULL"),
                postgresql_concurrently=True,
            )


def upgrade() -> None:
    _backfill_index(create=True)
    _replace_checks(add_memory=True)
    op.create_table(
        "memory_inbox_rules",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("mode", sa.String(length=8), server_default="off", nullable=False),
        sa.Column(
            "recipient_ids",
            postgresql.ARRAY(sa.UUID()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "sources",
            postgresql.ARRAY(sa.String(length=16)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("include_review", sa.Boolean(), server_default="false", nullable=False),
        sa.CheckConstraint(
            "mode IN ('off', 'shadow', 'live')", name=op.f("memory_inbox_rules_mode_check")
        ),
        sa.CheckConstraint(
            "cardinality(recipient_ids) <= 50",
            name=op.f("memory_inbox_rules_recipient_limit_check"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("memory_inbox_rules_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id", name=op.f("memory_inbox_rules_pkey")),
    )
    op.create_table(
        "memory_object_backfills",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cursor_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cursor_id", sa.Uuid(), nullable=True),
        sa.Column("scanned", sa.Integer(), server_default="0", nullable=False),
        sa.Column("linked", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("memory_object_backfills_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id", name=op.f("memory_object_backfills_pkey")),
    )
    op.create_table(
        "memory_object_merges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column(
            "merged_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "source_id <> target_id", name=op.f("memory_object_merges_distinct_objects_check")
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["memory_objects.id"],
            name=op.f("memory_object_merges_source_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["memory_objects.id"],
            name=op.f("memory_object_merges_target_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("memory_object_merges_pkey")),
    )
    op.create_index(
        "ix_memory_object_merges_active_target",
        "memory_object_merges",
        ["target_id", "source_id"],
        unique=False,
        postgresql_where=sa.text("undone_at IS NULL"),
    )
    op.create_index(
        "ix_memory_object_merges_source", "memory_object_merges", ["source_id"], unique=False
    )
    op.create_index(
        "ix_memory_object_merges_target", "memory_object_merges", ["target_id"], unique=False
    )
    op.create_index(
        "uq_memory_object_merges_active_source",
        "memory_object_merges",
        ["source_id"],
        unique=True,
        postgresql_where=sa.text("undone_at IS NULL"),
    )
    op.create_table(
        "memory_inbox_decisions",
        sa.Column("claim_id", sa.UUID(), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("revision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recipient_id", sa.UUID(), nullable=False),
        sa.Column("change", sa.String(length=16), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('shadow', 'delivered', 'muted')",
            name=op.f("memory_inbox_decisions_outcome_check"),
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["memory_claims.id"],
            name=op.f("memory_inbox_decisions_claim_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("memory_inbox_decisions_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["users.id"],
            name=op.f("memory_inbox_decisions_recipient_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "claim_id",
            "rule_version",
            "policy_version",
            "revision_at",
            "recipient_id",
            "change",
            name=op.f("memory_inbox_decisions_pkey"),
        ),
    )
    op.create_index(
        "ix_memory_inbox_decisions_org_rule",
        "memory_inbox_decisions",
        ["organization_id", "rule_version"],
        unique=False,
    )
    op.create_index(
        "ix_memory_inbox_decisions_recipient",
        "memory_inbox_decisions",
        ["recipient_id"],
        unique=False,
    )


def downgrade() -> None:
    _backfill_index(create=False)
    _replace_checks(add_memory=False)
    op.drop_index("ix_memory_inbox_decisions_recipient", table_name="memory_inbox_decisions")
    op.drop_index("ix_memory_inbox_decisions_org_rule", table_name="memory_inbox_decisions")
    op.drop_table("memory_inbox_decisions")
    op.drop_index(
        "uq_memory_object_merges_active_source",
        table_name="memory_object_merges",
        postgresql_where=sa.text("undone_at IS NULL"),
    )
    op.drop_index("ix_memory_object_merges_target", table_name="memory_object_merges")
    op.drop_index("ix_memory_object_merges_source", table_name="memory_object_merges")
    op.drop_index(
        "ix_memory_object_merges_active_target",
        table_name="memory_object_merges",
        postgresql_where=sa.text("undone_at IS NULL"),
    )
    op.drop_table("memory_object_merges")
    op.drop_table("memory_object_backfills")
    op.drop_table("memory_inbox_rules")
