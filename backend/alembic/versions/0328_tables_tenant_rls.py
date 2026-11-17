"""Install the complete Tables policy family without activating enforcement.

Revision ID: 0328_tables_tenant_rls
Revises: 0327_virtual_table_relations

The operator activates ENABLE/FORCE only after upgrading and draining every API
and worker, provisioning separate credentials and passing the read-only preflight.
This migration creates no roles, changes no credentials and deletes no legacy data.
SQL and policy fingerprints are frozen here, independent of mutable runtime code.
"""

import hashlib
import json

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0328_tables_tenant_rls"
down_revision = "0327_virtual_table_relations"
branch_labels = None
depends_on = None

_GUARD = "t3os_tables_tenant_guard"
_ACCESS = "t3os_tables_tenant_access"
_VERSION = "t3os.tables.rls.v1"
_ORGANIZATION = "organization_id = NULLIF(current_setting('t3os.organization_id', true), '')::uuid"
_MAINTENANCE = (
    "COALESCE(pg_catalog.pg_has_role(current_user, "
    "pg_catalog.to_regrole('t3os_tables_maintenance'), 'MEMBER'), false)"
)
_POLICIES = dict.fromkeys(
    (
        "virtual_tables",
        "virtual_table_records",
        "virtual_table_record_history",
        "virtual_table_receipts",
        "virtual_table_outbox",
        "virtual_table_media",
        "table_views",
        "virtual_table_relations",
        "virtual_table_record_links",
        "virtual_table_link_evidence",
    ),
    _ORGANIZATION,
)
_POLICIES.update(
    {
        "virtual_table_schema_versions": (
            "EXISTS (SELECT 1 FROM public.virtual_tables AS parent "
            "WHERE parent.id = virtual_table_schema_versions.table_id AND "
            "parent.organization_id = NULLIF(current_setting('t3os.organization_id', true), '')::uuid)"
        ),
        "virtual_table_trigger_revisions": (
            "EXISTS (SELECT 1 FROM public.virtual_table_triggers AS parent "
            "WHERE parent.id = virtual_table_trigger_revisions.trigger_id AND "
            "parent.organization_id = NULLIF(current_setting('t3os.organization_id', true), '')::uuid)"
        ),
        "virtual_table_triggers": (
            "organization_id = NULLIF(current_setting('t3os.organization_id', true), '')::uuid "
            "AND EXISTS (SELECT 1 FROM public.virtual_tables AS parent "
            "WHERE parent.id = virtual_table_triggers.table_id "
            "AND parent.organization_id = virtual_table_triggers.organization_id)"
        ),
        "table_trigger_admissions": (
            "organization_id = NULLIF(current_setting('t3os.organization_id', true), '')::uuid "
            "AND EXISTS (SELECT 1 FROM public.virtual_table_triggers AS parent "
            "WHERE parent.id = table_trigger_admissions.trigger_id "
            "AND parent.organization_id = table_trigger_admissions.organization_id) "
            "AND (outbox_event_id IS NULL OR EXISTS "
            "(SELECT 1 FROM public.virtual_table_outbox AS event "
            "WHERE event.id = table_trigger_admissions.outbox_event_id "
            "AND event.organization_id = table_trigger_admissions.organization_id))"
        ),
        "resource_grants": (
            "resource_type NOT IN ('table', 'table_record') OR ("
            "organization_id = NULLIF(current_setting('t3os.organization_id', true), '')::uuid)"
        ),
    }
)


def _refuse_active(connection: sa.Connection) -> None:
    active = connection.scalar(
        sa.text(
            "SELECT count(*) FROM pg_catalog.pg_class AS c "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname = ANY(:objects) "
            "AND (c.relrowsecurity OR c.relforcerowsecurity)"
        ),
        {"objects": list(_POLICIES)},
    )
    if active:
        raise RuntimeError(
            "Tables RLS is active. Drain every API/worker and explicitly disable and unforce "
            "the complete policy family before installing or downgrading this migration."
        )


def _refuse_legacy_corruption(connection: sa.Connection) -> None:
    row = connection.execute(
        sa.text(
            "SELECT "
            "(SELECT count(*) FROM public.virtual_table_triggers AS child "
            "JOIN public.virtual_tables AS parent ON parent.id = child.table_id "
            "WHERE child.organization_id <> parent.organization_id) AS triggers, "
            "(SELECT count(*) FROM public.table_trigger_admissions AS child "
            "JOIN public.virtual_table_triggers AS parent ON parent.id = child.trigger_id "
            "LEFT JOIN public.virtual_table_outbox AS event ON event.id = child.outbox_event_id "
            "WHERE child.organization_id <> parent.organization_id "
            "OR child.organization_id <> event.organization_id) AS admissions, "
            "(SELECT count(*) FROM public.resource_grants AS grant_row "
            "WHERE grant_row.resource_type IN ('table', 'table_record') "
            "AND grant_row.subject_user_id IS NOT NULL AND NOT EXISTS "
            "(SELECT 1 FROM public.organization_members AS member "
            "WHERE member.organization_id = grant_row.organization_id "
            "AND member.user_id = grant_row.subject_user_id)) AS grants"
        )
    ).one()
    if row.triggers or row.admissions or row.grants:
        raise RuntimeError(
            f"Tables legacy parent mismatch: triggers={row.triggers}, "
            f"admissions={row.admissions}, orphan_user_grants={row.grants}. "
            "Review the affected rows with the migration owner before retrying. "
            "No grant, trigger or admission was deleted or reparented."
        )


def _install_policies(connection: sa.Connection) -> None:
    for name, tenant in _POLICIES.items():
        expression = f"({tenant}) OR ({_MAINTENANCE})"
        for policy in (_GUARD, _ACCESS):
            op.execute(sa.text(f'DROP POLICY IF EXISTS "{policy}" ON public."{name}"'))
        op.execute(
            sa.text(
                f'CREATE POLICY "{_GUARD}" ON public."{name}" AS RESTRICTIVE '
                f"FOR ALL TO PUBLIC USING ({expression}) WITH CHECK ({expression})"
            )
        )
        op.execute(
            sa.text(
                f'CREATE POLICY "{_ACCESS}" ON public."{name}" AS PERMISSIVE '
                "FOR ALL TO PUBLIC USING (true) WITH CHECK (true)"
            )
        )
        # The internal "char" command tag is bytes under asyncpg, text under
        # psycopg2. The explicit cast keeps policy fingerprints driver-independent.
        rows = connection.execute(
            sa.text(
                "SELECT p.polname, p.polqual::text AS qual, p.polwithcheck::text AS check, "
                "p.polpermissive AS permissive, p.polcmd::text AS cmd, p.polroles AS roles, "
                "pg_catalog.current_setting('server_version_num') AS server_version "
                "FROM pg_catalog.pg_policy AS p "
                "JOIN pg_catalog.pg_class AS c ON c.oid = p.polrelid "
                "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relname = :name"
            ),
            {"name": name},
        ).mappings()
        for row in rows:
            definition = [row[key] for key in ("qual", "check", "permissive", "cmd", "roles")]
            digest = hashlib.sha256(
                json.dumps(definition, separators=(",", ":")).encode()
            ).hexdigest()
            major = int(row["server_version"]) // 10000
            stamp = f"{_VERSION}.pg{major}:{digest}"
            policy = row["polname"]
            # Fixed policy identifiers and a fixed version/major/hex digest only.
            op.execute(sa.text(f'COMMENT ON POLICY "{policy}" ON public."{name}" IS \'{stamp}\''))


def upgrade() -> None:
    connection = op.get_bind()
    _refuse_active(connection)
    _refuse_legacy_corruption(connection)
    unknown = connection.scalar(
        sa.text(
            "SELECT count(*) FROM pg_catalog.pg_policy AS p "
            "JOIN pg_catalog.pg_class AS c ON c.oid = p.polrelid "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname = ANY(:objects) "
            "AND p.polname NOT IN (:guard, :access)"
        ),
        {"objects": list(_POLICIES), "guard": _GUARD, "access": _ACCESS},
    )
    if unknown:
        raise RuntimeError("Unexpected Tables policies exist; review them before migration")
    op.add_column(
        "resource_grants",
        sa.Column(
            "table_subject_user_id",
            postgresql.UUID(as_uuid=True),
            sa.Computed(
                "CASE WHEN resource_type IN ('table', 'table_record') THEN subject_user_id END",
                persisted=True,
            ),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_resource_grants_table_member",
        "resource_grants",
        "organization_members",
        ["organization_id", "table_subject_user_id"],
        ["organization_id", "user_id"],
        ondelete="CASCADE",
        match="SIMPLE",
    )
    op.create_index(
        "ix_resource_grants_table_member",
        "resource_grants",
        ["organization_id", "table_subject_user_id"],
        postgresql_where=sa.text("table_subject_user_id IS NOT NULL"),
    )
    _install_policies(connection)


def downgrade() -> None:
    _refuse_active(op.get_bind())
    for name in _POLICIES:
        for policy in (_GUARD, _ACCESS):
            op.execute(sa.text(f'DROP POLICY IF EXISTS "{policy}" ON public."{name}"'))
    op.drop_index("ix_resource_grants_table_member", table_name="resource_grants")
    op.drop_constraint("fk_resource_grants_table_member", "resource_grants", type_="foreignkey")
    op.drop_column("resource_grants", "table_subject_user_id")
