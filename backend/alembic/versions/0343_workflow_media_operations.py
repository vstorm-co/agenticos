"""Preserve media submissions, reservations and output identity across worker loss.

Revision ID: 0343_workflow_media_operations
Revises: 0342_browser_credential_plans

Four existing-table lineage keys are built concurrently with exact retry guards.
Attaching them needs brief locks; rehearse lock waits before deployment. The new
empty table has no historical backfill. A downgrade refuses every populated
operation table, including completed evidence, rather than discarding receipts.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0343_workflow_media_operations"
down_revision: str | None = "0342_browser_credential_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEYS = (
    ("workflow_runs", "uq_workflow_runs_org_id", ("organization_id", "id")),
    ("node_runs", "uq_node_runs_org_run_id", ("organization_id", "workflow_run_id", "id")),
    ("node_attempts", "uq_node_attempts_org_node_id", ("organization_id", "node_run_id", "id")),
    (
        "workflow_files",
        "uq_workflow_files_org_run_id",
        ("organization_id", "workflow_run_id", "id"),
    ),
)


def _building(table: str) -> bool:
    return bool(
        op.get_bind().scalar(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM pg_stat_progress_create_index p "
                "JOIN pg_locks l ON l.pid = p.pid "
                "WHERE p.pid <> pg_backend_pid() AND l.locktype = 'relation' "
                "AND l.database = (SELECT oid FROM pg_database WHERE datname = current_database()) "
                "AND l.relation = to_regclass(:table))"
            ),
            {"table": table},
        )
    )


def _index_state(table: str, name: str, columns: tuple[str, ...]) -> tuple[bool, bool] | None:
    row = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT CASE WHEN c.relkind = 'i' THEN "
                "i.indrelid = to_regclass(:table) AND i.indisunique AND i.indimmediate "
                "AND NOT i.indisprimary AND NOT i.indisexclusion AND NOT i.indnullsnotdistinct "
                "AND i.indnkeyatts = :width AND i.indnatts = :width "
                "AND i.indexprs IS NULL AND i.indpred IS NULL AND a.amname = 'btree' "
                "AND NOT EXISTS (SELECT 1 FROM unnest(i.indoption::smallint[]) v WHERE v <> 0) "
                "AND NOT EXISTS (SELECT 1 FROM unnest(i.indcollation::oid[]) v WHERE v <> 0) "
                "AND NOT EXISTS (SELECT 1 FROM unnest(i.indclass::oid[]) v WHERE v <> "
                "(SELECT o.oid FROM pg_opclass o WHERE o.opcmethod = a.oid "
                "AND o.opcnamespace = 'pg_catalog'::regnamespace AND o.opcname = 'uuid_ops' "
                "AND o.opcintype = 'uuid'::regtype AND o.opcdefault)) "
                "AND ARRAY(SELECT pg_get_indexdef(c.oid, p, false) "
                "FROM generate_series(1, :width) p) = CAST(:columns AS text[]) "
                "AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conindid = c.oid) "
                "ELSE false END AS expected, "
                "i.indisvalid AND i.indisready AND i.indislive AS usable "
                "FROM pg_class c LEFT JOIN pg_index i ON i.indexrelid = c.oid "
                "LEFT JOIN pg_am a ON a.oid = c.relam WHERE c.oid = to_regclass(:name)"
            ),
            {"table": table, "name": name, "columns": list(columns), "width": len(columns)},
        )
        .one_or_none()
    )
    return None if row is None else (bool(row.expected), bool(row.usable))


def _check(table: str, name: str, columns: tuple[str, ...]) -> tuple[bool, bool] | None:
    if _building(table):
        raise RuntimeError(
            f"An index on {table} is being built; let it finish before revision 0343."
        )
    state = _index_state(table, name, columns)
    if state is not None and not state[0]:
        raise RuntimeError(
            f"Existing {name} is not the expected standalone lineage key; reconcile it before revision 0343."
        )
    return state


def _lineage_keys() -> None:
    for table, name, columns in _KEYS:
        _check(table, name, columns)
    with op.get_context().autocommit_block():
        for table, name, columns in _KEYS:
            state = _check(table, name, columns)
            if state is not None and state[1]:
                continue
            if state is not None:
                op.drop_index(name, table_name=table, postgresql_concurrently=True)
            op.create_index(name, table, list(columns), unique=True, postgresql_concurrently=True)
    for table, name, _columns in _KEYS:
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} UNIQUE USING INDEX {name}")


def upgrade() -> None:
    _lineage_keys()
    op.create_table(
        "workflow_media_operations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workflow_run_id", sa.UUID(), nullable=False),
        sa.Column("node_run_id", sa.UUID(), nullable=False),
        sa.Column("origin_attempt_id", sa.UUID(), nullable=False),
        sa.Column("collector_attempt_id", sa.UUID(), nullable=False),
        sa.Column("collector_token", sa.UUID(), nullable=False),
        sa.Column("submission_token", sa.UUID(), nullable=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("media_kind", sa.String(8), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("provider_api", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("pricing_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("cost_evidence", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("secret_id", sa.UUID(), nullable=False),
        sa.Column("secret_generation", sa.UUID(), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("provider_receipt", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("effect_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("reserved_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("held_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("incurred_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("booked_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("cost_source", sa.String(24), nullable=True),
        sa.Column(
            "accounting_complete", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("reserved_bytes", sa.BigInteger(), nullable=False),
        sa.Column("held_bytes", sa.BigInteger(), nullable=False),
        sa.Column("output_file_id", sa.UUID(), nullable=False),
        sa.Column("output_filename", sa.String(255), nullable=False),
        sa.Column("output_sha256", sa.String(64), nullable=True),
        sa.Column("output_metadata", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("stored_file_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id", "workflow_run_id"],
            ["workflow_runs.organization_id", "workflow_runs.id"],
            name="fk_media_operation_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workflow_run_id", "node_run_id"],
            ["node_runs.organization_id", "node_runs.workflow_run_id", "node_runs.id"],
            name="fk_media_operation_node",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "node_run_id", "origin_attempt_id"],
            ["node_attempts.organization_id", "node_attempts.node_run_id", "node_attempts.id"],
            name="fk_media_operation_origin",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "node_run_id", "collector_attempt_id"],
            ["node_attempts.organization_id", "node_attempts.node_run_id", "node_attempts.id"],
            name="fk_media_operation_collector",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workflow_run_id", "stored_file_id"],
            [
                "workflow_files.organization_id",
                "workflow_files.workflow_run_id",
                "workflow_files.id",
            ],
            name="fk_media_operation_output",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.UniqueConstraint(
            "organization_id", "origin_attempt_id", name="uq_media_operation_origin"
        ),
        sa.UniqueConstraint("organization_id", "output_file_id", name="uq_media_operation_output"),
        sa.CheckConstraint("media_kind IN ('image', 'video')", name="ck_media_operation_kind"),
        sa.CheckConstraint(
            "jsonb_typeof(pricing_snapshot) = 'object' AND octet_length(pricing_snapshot::text) <= 16384",
            name="ck_media_operation_pricing_snapshot",
        ),
        sa.CheckConstraint(
            "cost_evidence IS NULL OR (jsonb_typeof(cost_evidence) = 'object' AND octet_length(cost_evidence::text) <= 4096)",
            name="ck_media_operation_cost_evidence",
        ),
        sa.CheckConstraint(
            "(submission_token IS NULL) = (effect_started_at IS NULL)",
            name="ck_media_operation_submission_token",
        ),
        sa.CheckConstraint(
            "phase IN ('prepared', 'submitting', 'submitted', 'collecting', 'stored', 'unknown', 'failed', 'cancelled')",
            name="ck_media_operation_phase",
        ),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'", name="ck_media_operation_request_hash"
        ),
        sa.CheckConstraint(
            "output_sha256 IS NULL OR output_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_media_operation_output_hash",
        ),
        sa.CheckConstraint(
            "reserved_usd > 0 AND reserved_usd <= 999999.999999 "
            "AND held_usd BETWEEN 0 AND reserved_usd AND incurred_usd BETWEEN 0 AND 999999.999999 "
            "AND booked_usd BETWEEN 0 AND incurred_usd",
            name="ck_media_operation_costs",
        ),
        sa.CheckConstraint(
            "cost_source IS NULL OR cost_source IN ('reported', 'catalog_estimate')",
            name="ck_media_operation_cost_source",
        ),
        sa.CheckConstraint(
            "(incurred_usd = 0 OR cost_source IS NOT NULL) AND (NOT accounting_complete OR held_usd = 0)",
            name="ck_media_operation_accounting",
        ),
        sa.CheckConstraint(
            "reserved_bytes BETWEEN 1 AND 268435456 AND held_bytes BETWEEN 0 AND reserved_bytes",
            name="ck_media_operation_bytes",
        ),
        sa.CheckConstraint(
            "(output_sha256 IS NULL) = (output_metadata IS NULL) AND (output_metadata IS NULL OR jsonb_typeof(output_metadata) = 'object')",
            name="ck_media_operation_output_metadata",
        ),
        sa.CheckConstraint(
            "(phase = 'stored') = (stored_file_id IS NOT NULL) "
            "AND (stored_file_id IS NULL OR (stored_file_id = output_file_id AND output_sha256 IS NOT NULL AND held_bytes = 0))",
            name="ck_media_operation_stored_identity",
        ),
        sa.CheckConstraint(
            "provider_receipt IS NULL OR (jsonb_typeof(provider_receipt) = 'object' "
            "AND provider_receipt ?& ARRAY['provider','api','model','kind','id'] "
            "AND provider_receipt - ARRAY['provider','api','model','kind','id'] = '{}'::jsonb "
            "AND provider_receipt->'provider' = to_jsonb(provider) "
            "AND provider_receipt->'api' = to_jsonb(provider_api) "
            "AND provider_receipt->'model' = to_jsonb(model) "
            "AND jsonb_typeof(provider_receipt->'kind') = 'string' "
            "AND provider_receipt->>'kind' IN ('job','file','response') "
            "AND jsonb_typeof(provider_receipt->'id') = 'string' "
            "AND length(provider_receipt->>'id') BETWEEN 1 AND 1024)",
            name="ck_media_operation_receipt",
        ),
        sa.CheckConstraint(
            "(phase <> 'submitted' OR provider_receipt IS NOT NULL) "
            "AND (provider_receipt IS NULL OR (submitted_at IS NOT NULL AND effect_started_at IS NOT NULL))",
            name="ck_media_operation_submission",
        ),
    )
    op.create_index(
        "uq_media_operation_current",
        "workflow_media_operations",
        ["organization_id", "node_run_id"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    op.create_index(
        "ix_media_operation_run",
        "workflow_media_operations",
        ["organization_id", "workflow_run_id"],
    )
    for column, suffix in (
        ("node_run_id", "node"),
        ("origin_attempt_id", "origin"),
        ("collector_attempt_id", "collector"),
        ("stored_file_id", "file"),
    ):
        op.create_index(f"ix_media_operation_{suffix}", "workflow_media_operations", [column])
    op.create_index(
        "ix_media_operation_unresolved",
        "workflow_media_operations",
        ["organization_id", "workflow_run_id"],
        postgresql_where=sa.text("held_usd > 0 OR held_bytes > 0 OR incurred_usd > booked_usd"),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM workflow_media_operations)")):
        raise RuntimeError(
            "Revision 0343 retains media receipts and holds; reconcile and archive them before downgrade."
        )
    op.drop_table("workflow_media_operations")
    for table, name, _columns in reversed(_KEYS):
        # Static revision-owned names; a key already gone must not block the downgrade.
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
