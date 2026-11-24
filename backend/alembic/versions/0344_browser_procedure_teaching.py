"""Bound structural browser recordings and preserve reviewed skill provenance.

Revision ID: 0344_browser_procedure_teaching
Revises: 0343_workflow_media_operations

Nullable metadata columns are added without a backfill. Existing-table indexes
are built concurrently with exact interrupted-build guards; their attachment and
the skill source check need brief locks. Rehearse these locks before deployment.
A populated teaching table or saved procedure refuses destructive downgrade.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0344_browser_procedure_teaching"
down_revision: str | None = "0343_workflow_media_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT = "uq_skill_proposals_tenant"
_SOURCE = "uq_skill_proposal_browser_source"
_OLD_SOURCES = "'backfill', 'created', 'edit', 'resources', 'library', 'workspace', 'improve', 'restore', 'catch_up', 'from_fork'"
_NEW_SOURCES = "'backfill', 'created', 'edit', 'resources', 'library', 'workspace', 'improve', 'browser_teaching', 'restore', 'catch_up', 'from_fork'"
_TABLES = (
    "browser_teaching_policies",
    "browser_teaching_preferences",
    "browser_procedure_teaching_sessions",
)


def _building() -> bool:
    return bool(
        op.get_bind().scalar(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM pg_stat_progress_create_index p "
                "JOIN pg_locks l ON l.pid = p.pid WHERE p.pid <> pg_backend_pid() "
                "AND l.locktype = 'relation' AND l.database = "
                "(SELECT oid FROM pg_database WHERE datname = current_database()) "
                "AND l.relation = to_regclass('skill_proposals'))"
            )
        )
    )


def _state(name: str) -> tuple[bool, bool] | None:
    row = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT c.relkind = 'i' AND i.indrelid = to_regclass('skill_proposals') "
                "AND i.indisunique AND i.indimmediate AND NOT i.indisprimary "
                "AND NOT i.indisexclusion AND NOT i.indnullsnotdistinct "
                "AND i.indnkeyatts = 2 AND i.indnatts = 2 AND a.amname = 'btree' "
                "AND NOT EXISTS (SELECT 1 FROM unnest(i.indoption::smallint[]) v WHERE v <> 0) "
                "AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conindid = c.oid) AS expected, "
                "i.indisvalid AND i.indisready AND i.indislive AS usable, "
                "ARRAY(SELECT at.attname FROM unnest(i.indkey) WITH ORDINALITY k(attnum, n) "
                "LEFT JOIN pg_attribute at ON at.attrelid = i.indrelid AND at.attnum = k.attnum "
                "ORDER BY k.n) AS columns, "
                "ARRAY(SELECT opc.opcname FROM unnest(i.indclass) WITH ORDINALITY k(opcid, n) "
                "JOIN pg_opclass opc ON opc.oid = k.opcid ORDER BY k.n) AS classes, "
                "NOT EXISTS (SELECT 1 FROM unnest(i.indclass) k(opcid) JOIN pg_opclass opc ON opc.oid = k.opcid "
                "WHERE opc.opcnamespace <> 'pg_catalog'::regnamespace OR NOT opc.opcdefault) AS default_classes, "
                "NOT EXISTS (SELECT 1 FROM unnest(i.indcollation) k(collid) "
                "WHERE k.collid <> 0 AND k.collid <> "
                "(SELECT oid FROM pg_collation WHERE collname = 'default' AND collnamespace = 'pg_catalog'::regnamespace)) AS default_collation, "
                "pg_get_expr(i.indexprs, i.indrelid) AS expression, pg_get_expr(i.indpred, i.indrelid) AS predicate "
                "FROM pg_class c LEFT JOIN pg_index i ON i.indexrelid = c.oid "
                "LEFT JOIN pg_am a ON a.oid = c.relam WHERE c.oid = to_regclass(:name)"
            ),
            {"name": name},
        )
        .one_or_none()
    )
    if row is None:
        return None
    shape = (
        (
            list(row.columns) == ["id", "organization_id"]
            and list(row.classes) == ["uuid_ops", "uuid_ops"]
            and row.expression is None
            and row.predicate is None
        )
        if name == _TENANT
        else (
            list(row.columns) == ["organization_id", None]
            and list(row.classes) == ["uuid_ops", "text_ops"]
            and row.expression == "(browser_procedure ->> 'source_session_id'::text)"
            and row.predicate == "(browser_procedure IS NOT NULL)"
        )
    )
    return (
        bool(row.expected and row.default_classes and row.default_collation and shape),
        bool(row.usable),
    )


def _check(name: str) -> tuple[bool, bool] | None:
    if _building():
        raise RuntimeError(
            "A skill-proposal index is being built; let it finish before revision 0344."
        )
    state = _state(name)
    if state is not None and not state[0]:
        raise RuntimeError(
            f"Existing {name} is not the expected standalone teaching index; reconcile it before revision 0344."
        )
    return state


def _metadata_columns() -> None:
    # A concurrent build commits these two nullable columns. A retry accepts
    # only their exact shape and never deletes or rewrites an existing value.
    for table in ("skill_proposals", "skill_versions"):
        column = next(
            (
                item
                for item in sa.inspect(op.get_bind()).get_columns(table)
                if item["name"] == "browser_procedure"
            ),
            None,
        )
        if column is None:
            op.add_column(
                table,
                sa.Column(
                    "browser_procedure",
                    postgresql.JSONB(none_as_null=True),
                    nullable=True,
                ),
            )
        elif (
            not isinstance(column["type"], postgresql.JSONB)
            or not column["nullable"]
            or column["default"] is not None
        ):
            raise RuntimeError(
                f"Existing {table}.browser_procedure has an unexpected shape; reconcile revision 0344."
            )


def _indexes() -> None:
    for name in (_TENANT, _SOURCE):
        _check(name)
    _metadata_columns()
    with op.get_context().autocommit_block():
        for name in (_TENANT, _SOURCE):
            state = _check(name)
            if state is not None and state[1]:
                continue
            if state is not None:
                op.drop_index(name, table_name="skill_proposals", postgresql_concurrently=True)
            if name == _TENANT:
                op.create_index(
                    name,
                    "skill_proposals",
                    ["id", "organization_id"],
                    unique=True,
                    postgresql_concurrently=True,
                )
            else:
                op.create_index(
                    name,
                    "skill_proposals",
                    ["organization_id", sa.text("(browser_procedure->>'source_session_id')")],
                    unique=True,
                    postgresql_where=sa.text("browser_procedure IS NOT NULL"),
                    postgresql_concurrently=True,
                )
    op.execute(f"ALTER TABLE skill_proposals ADD CONSTRAINT {_TENANT} UNIQUE USING INDEX {_TENANT}")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    _indexes()
    op.drop_constraint(
        op.f("skill_versions_ck_skill_version_source_check"), "skill_versions", type_="check"
    )
    op.create_check_constraint(
        "ck_skill_version_source", "skill_versions", f"source IN ({_NEW_SOURCES})"
    )
    op.create_table(
        "browser_teaching_policies",
        sa.Column("organization_id", sa.UUID(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("generation", sa.UUID(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "browser_teaching_preferences",
        sa.Column("organization_id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), primary_key=True),
        sa.Column("agent_id", sa.UUID(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("generation", sa.UUID(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["organization_id", "agent_id"],
            ["agents.organization_id", "agents.id"],
            ondelete="CASCADE",
            name="fk_teaching_preference_agent",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_members.organization_id", "organization_members.user_id"],
            ondelete="CASCADE",
            name="fk_teaching_preference_member",
        ),
    )
    op.create_table(
        "browser_procedure_teaching_sessions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("controller_id", sa.UUID(), nullable=False),
        sa.Column("takeover_id", sa.UUID(), nullable=True),
        sa.Column("connection_id", sa.UUID(), nullable=True),
        sa.Column("call_id", sa.String(200), nullable=False),
        sa.Column("tab_id", sa.String(200), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("allowed_origins", postgresql.JSONB(), nullable=False),
        sa.Column("target_skill_id", sa.UUID(), nullable=True),
        sa.Column("target_base_version", sa.Integer(), nullable=True),
        sa.Column("target_base_version_id", sa.UUID(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column(
            "browser_completed", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "verified_success", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("policy_generation", sa.UUID(), nullable=False),
        sa.Column("preference_generation", sa.UUID(), nullable=True),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column(
            "sanitized_events",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("review", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("procedure", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("source_hash", sa.String(64), nullable=True),
        sa.Column("generation_state", sa.String(16), nullable=False, server_default="none"),
        sa.Column("generation_mode", sa.String(16), nullable=True),
        sa.Column("generation_token", sa.UUID(), nullable=True),
        sa.Column("generation_revision", sa.Integer(), nullable=True),
        sa.Column("generation_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("proposal_id", sa.UUID(), nullable=True),
        sa.Column("capture_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("organization_id", "id", name="uq_browser_procedure_teaching_tenant"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id", "owner_user_id"],
            ["organization_members.organization_id", "organization_members.user_id"],
            ondelete="CASCADE",
            name="fk_browser_procedure_teaching_owner",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "agent_id"],
            ["agents.organization_id", "agents.id"],
            ondelete="CASCADE",
            name="fk_browser_procedure_teaching_agent",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "run_id"],
            ["agent_runs.organization_id", "agent_runs.id"],
            ondelete="CASCADE",
            name="fk_browser_procedure_teaching_run",
        ),
        sa.ForeignKeyConstraint(
            ["target_skill_id", "organization_id"],
            ["skills.id", "skills.organization_id"],
            ondelete="CASCADE",
            name="fk_browser_procedure_teaching_skill",
        ),
        sa.ForeignKeyConstraint(
            ["target_base_version_id", "organization_id"],
            ["skill_versions.id", "skill_versions.organization_id"],
            ondelete="CASCADE",
            name="fk_browser_procedure_teaching_skill_version",
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id", "organization_id"],
            ["skill_proposals.id", "skill_proposals.organization_id"],
            ondelete="CASCADE",
            name="fk_browser_procedure_teaching_proposal",
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'refinement')", name="ck_browser_procedure_teaching_source"
        ),
        sa.CheckConstraint(
            "(source = 'manual' AND takeover_id IS NOT NULL AND connection_id IS NOT NULL "
            "AND preference_generation IS NULL AND NOT browser_completed AND NOT verified_success) OR "
            "(source = 'refinement' AND takeover_id IS NULL AND connection_id IS NULL "
            "AND preference_generation IS NOT NULL AND (NOT verified_success OR browser_completed))",
            name="ck_browser_procedure_teaching_provenance",
        ),
        sa.CheckConstraint(
            "status IN ('recording', 'paused', 'review', 'proposed', 'discarded', 'expired')",
            name="ck_browser_procedure_teaching_state",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_browser_procedure_teaching_revision"),
        sa.CheckConstraint(
            "jsonb_typeof(sanitized_events) = 'array' AND jsonb_array_length(sanitized_events) <= 500 "
            "AND octet_length(sanitized_events::text) <= 131072",
            name="ck_browser_procedure_teaching_event_limit",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_origins) = 'array' AND jsonb_array_length(allowed_origins) <= 10",
            name="ck_browser_procedure_teaching_origin_limit",
        ),
        sa.CheckConstraint(
            "generation_state IN ('none', 'queued', 'generating', 'succeeded', 'refused', 'unknown', 'cancelled')",
            name="ck_browser_procedure_teaching_generation",
        ),
        sa.CheckConstraint(
            "generation_mode IS NULL OR generation_mode IN ('reviewed', 'assistant')",
            name="ck_browser_procedure_teaching_generation_mode",
        ),
        sa.CheckConstraint(
            "max_cost_usd IS NULL OR (max_cost_usd > 0 AND max_cost_usd <= 10)",
            name="ck_browser_procedure_teaching_budget",
        ),
        sa.CheckConstraint(
            "generation_state NOT IN ('queued', 'generating', 'succeeded', 'unknown') OR "
            "(generation_token IS NOT NULL AND generation_revision IS NOT NULL AND source_hash IS NOT NULL)",
            name="ck_browser_procedure_teaching_generation_claim",
        ),
        sa.CheckConstraint(
            "status != 'proposed' OR proposal_id IS NOT NULL",
            name="ck_browser_procedure_teaching_proposal",
        ),
    )
    op.create_index(
        "ix_browser_procedure_teaching_owner",
        "browser_procedure_teaching_sessions",
        ["organization_id", "owner_user_id", "created_at"],
    )
    op.create_index(
        "ix_browser_procedure_teaching_expiry",
        "browser_procedure_teaching_sessions",
        ["expires_at"],
    )
    op.create_index(
        "uq_browser_procedure_teaching_active_view",
        "browser_procedure_teaching_sessions",
        ["organization_id", "run_id", "call_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('recording', 'paused')"),
    )


def downgrade() -> None:
    populated = any(
        op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")) for table in _TABLES
    )
    populated = populated or bool(
        op.get_bind().scalar(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM skill_proposals WHERE browser_procedure IS NOT NULL) "
                "OR EXISTS (SELECT 1 FROM skill_versions WHERE browser_procedure IS NOT NULL OR source = 'browser_teaching')"
            )
        )
    )
    if populated:
        raise RuntimeError(
            "Revision 0344 retains teaching decisions and procedure provenance; export and explicitly resolve them before downgrade."
        )
    for table in reversed(_TABLES):
        op.drop_table(table)
    op.drop_constraint(
        op.f("skill_versions_ck_skill_version_source_check"), "skill_versions", type_="check"
    )
    op.create_check_constraint(
        "ck_skill_version_source", "skill_versions", f"source IN ({_OLD_SOURCES})"
    )
    op.drop_index(_SOURCE, table_name="skill_proposals")
    op.drop_constraint(_TENANT, "skill_proposals", type_="unique")
    op.drop_column("skill_proposals", "browser_procedure")
    op.drop_column("skill_versions", "browser_procedure")
