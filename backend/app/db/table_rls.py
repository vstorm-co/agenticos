"""Database-enforced organization isolation for the Tables object family.

Policies are installed by migration and activated by the operator only after both
credentials and all entry points have been upgraded. The GUC is trusted application
context, not an authorization boundary against arbitrary SQL or application compromise.
Maintenance is a separate PostgreSQL role/connection, never a request-controlled flag.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import RowMapping, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConfigurationError
from app.db.table_tenant import ORGANIZATION_POLICY, UnsafeTableDatabaseRoleError, bind_table_tenant

if TYPE_CHECKING:
    from app.core.permissions import AuthContext

MAINTENANCE_ROLE = "t3os_tables_maintenance"
GUARD_POLICY = "t3os_tables_tenant_guard"
ACCESS_POLICY = "t3os_tables_tenant_access"
POLICY_VERSION = "t3os.tables.rls.v1"
_ACTIVE_TRANSACTION_KEY = "t3os_tables_rls_checked_transaction"

_ORGANIZATION_TABLES = (
    "virtual_tables",
    "virtual_table_records",
    "virtual_table_record_history",
    "virtual_table_receipts",
    "virtual_table_outbox",
    "virtual_table_media",
    "table_views",
    "virtual_table_triggers",
    "table_trigger_admissions",
    "virtual_table_relations",
    "virtual_table_record_links",
    "virtual_table_link_evidence",
)
TENANT_POLICIES = dict.fromkeys(_ORGANIZATION_TABLES, ORGANIZATION_POLICY)
TENANT_POLICIES.update(
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
        # Other resource families keep their existing authorization paths.
        "resource_grants": (
            "resource_type NOT IN ('table', 'table_record') OR (" + ORGANIZATION_POLICY + ")"
        ),
    }
)
TABLE_OBJECTS = tuple(sorted(TENANT_POLICIES))
MAINTENANCE_PREDICATE = (
    "COALESCE(pg_catalog.pg_has_role(current_user, "
    "pg_catalog.to_regrole('t3os_tables_maintenance'), 'MEMBER'), false)"
)


class TableRlsConfigurationError(ConfigurationError):
    """The installed schema or database roles cannot safely enforce Tables tenancy."""

    code = "TABLES_RLS_CONFIGURATION"


def _postgres_url(value: str) -> URL:
    try:
        url = make_url(value)
    except ArgumentError, ValueError:
        raise TableRlsConfigurationError("Invalid PostgreSQL credential URL") from None
    if url.get_backend_name() != "postgresql":
        raise TableRlsConfigurationError("Tables credentials must name PostgreSQL")
    if any(
        key.startswith("ssl") and not isinstance(option, str) for key, option in url.query.items()
    ):
        raise TableRlsConfigurationError("PostgreSQL TLS options must have one string value each")
    if "ssl" in url.query and "sslmode" in url.query and url.query["ssl"] != url.query["sslmode"]:
        raise TableRlsConfigurationError("PostgreSQL ssl and sslmode must not conflict")
    return url


def async_postgres_url(value: str) -> URL:
    """Select asyncpg for an operator DSN without ever rendering its password."""
    url = _postgres_url(value)
    query = dict(url.query)
    if "sslmode" in query:
        query["ssl"] = query.pop("sslmode")
    return url.set(drivername="postgresql+asyncpg", query=query)


def sync_postgres_url(value: str) -> URL:
    """Use the installed psycopg2 migration driver for provider or async DSNs."""
    url = _postgres_url(value)
    query = dict(url.query)
    if "ssl" in query:
        query["sslmode"] = query.pop("ssl")
    return url.set(drivername="postgresql+psycopg2", query=query)


@dataclass(frozen=True)
class TableRlsState:
    """Database state, read afresh; an inactive process cache could miss cutover."""

    present: frozenset[str]
    enabled: frozenset[str]
    forced: frozenset[str]

    @property
    def active(self) -> bool:
        if not self.enabled and not self.forced:
            return False
        expected = frozenset(TABLE_OBJECTS)
        if self.present != expected or self.enabled != expected or self.forced != expected:
            raise TableRlsConfigurationError(
                "Tables RLS is only partially enabled; finish or roll back the operator cutover"
            )
        return True


async def table_rls_state(db: AsyncSession) -> TableRlsState:
    rows = (
        await db.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_catalog.pg_class AS c "
                "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind = 'r' "
                "AND c.relname = ANY(:objects)"
            ),
            {"objects": list(TABLE_OBJECTS)},
        )
    ).all()
    return TableRlsState(
        present=frozenset(row.relname for row in rows),
        enabled=frozenset(row.relname for row in rows if row.relrowsecurity),
        forced=frozenset(row.relname for row in rows if row.relforcerowsecurity),
    )


async def require_table_connection_role(db: AsyncSession, *, maintenance: bool = False) -> str:
    """Check the login and every role it can assume, not only inherited privileges.

    Neither connection may own a protected table or assume an owner, superuser or
    BYPASSRLS role. A maintenance login gains its explicit policy exception through
    the NOLOGIN maintenance group. Runtime logins must have no path into that group.
    """
    row = (
        await db.execute(
            text(
                "SELECT current_user AS role_name, session_user AS login_name, "
                "EXISTS (SELECT 1 FROM pg_catalog.pg_roles AS r "
                "WHERE (r.rolsuper OR r.rolbypassrls OR r.rolcreaterole) "
                "AND (r.rolname = session_user OR "
                "pg_catalog.pg_has_role(current_user, r.oid, 'MEMBER') OR "
                "pg_catalog.pg_has_role(session_user, r.oid, 'MEMBER'))) AS unsafe_role, "
                "EXISTS (SELECT 1 FROM pg_catalog.pg_class AS c "
                "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relname = ANY(:objects) "
                "AND (pg_catalog.pg_has_role(current_user, c.relowner, 'MEMBER') OR "
                "pg_catalog.pg_has_role(session_user, c.relowner, 'MEMBER'))) AS owns_tables, "
                "COALESCE((SELECT r.rolcanlogin FROM pg_catalog.pg_roles AS r "
                "WHERE r.rolname = :maintenance_group), true) AS unsafe_group, "
                "EXISTS (SELECT 1 FROM pg_catalog.pg_class AS c "
                "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
                "CROSS JOIN pg_catalog.pg_roles AS r "
                "WHERE n.nspname = 'public' AND c.relname = ANY(:objects) "
                "AND (pg_catalog.pg_has_role(current_user, r.oid, 'MEMBER') OR "
                "pg_catalog.pg_has_role(session_user, r.oid, 'MEMBER')) "
                "AND pg_catalog.has_table_privilege(r.oid, c.oid, 'TRUNCATE')) AS can_truncate, "
                "EXISTS (SELECT 1 FROM pg_catalog.pg_class AS c "
                "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relname = ANY(:objects) "
                "AND NOT (pg_catalog.has_table_privilege(current_user, c.oid, 'SELECT') "
                "AND pg_catalog.has_table_privilege(current_user, c.oid, 'INSERT') "
                "AND pg_catalog.has_table_privilege(current_user, c.oid, 'UPDATE') "
                "AND pg_catalog.has_table_privilege(current_user, c.oid, 'DELETE'))) AS missing_dml, "
                "COALESCE(pg_catalog.pg_has_role(current_user, "
                "pg_catalog.to_regrole(:maintenance_group), 'MEMBER'), false) AS maintenance, "
                "COALESCE(pg_catalog.pg_has_role(session_user, "
                "pg_catalog.to_regrole(:maintenance_group), 'MEMBER'), false) AS login_maintenance"
            ),
            {"objects": list(TABLE_OBJECTS), "maintenance_group": MAINTENANCE_ROLE},
        )
    ).one()
    if (
        row.unsafe_role
        or row.owns_tables
        or row.can_truncate
        or row.missing_dml
        or bool(row.maintenance) != maintenance
        or bool(row.login_maintenance) != maintenance
        or (maintenance and row.unsafe_group)
    ):
        kind = "maintenance" if maintenance else "runtime"
        raise UnsafeTableDatabaseRoleError(
            f"Unsafe Tables {kind} role: require separate non-owner credentials without "
            "SUPERUSER, BYPASSRLS, CREATEROLE, TRUNCATE or an assumable privileged role; "
            "grant SELECT, INSERT, UPDATE and DELETE on the protected objects"
        )
    return str(row.role_name)


async def verify_table_runtime(db: AsyncSession) -> bool:
    """Fail closed on partial activation or privileged runtime credentials."""
    active = (await table_rls_state(db)).active
    if active:
        await require_table_policy_inventory(db)
        await require_table_connection_role(db)
    return active


async def bind_table_access(db: AsyncSession, ctx: AuthContext) -> None:
    """Bind after cutover while preserving legacy transactions before it.

    Inactive state is never cached. Active validation is cached only for the same
    outer transaction; the strict binder still checks the tenant on every call.
    This marker grants no maintenance authority and cannot widen database policies.
    """
    transaction = db.get_transaction()
    if transaction is not None and db.info.get(_ACTIVE_TRANSACTION_KEY) is transaction:
        await bind_table_tenant(db, ctx)
        return
    with db.no_autoflush:
        if not await verify_table_runtime(db):
            return
        await bind_table_tenant(db, ctx)
    db.info[_ACTIVE_TRANSACTION_KEY] = db.get_transaction()


async def same_table_database(runtime: AsyncSession, other: AsyncSession) -> None:
    """Prove two separate connections reach the same database without privileged metadata.

    Advisory locks are scoped to a database. A fresh random lock held by the runtime
    transaction must be unavailable on the other connection. Hostnames, proxy addresses
    and database names alone cannot establish that two DSNs reach the same database.
    """
    from secrets import randbits

    key = randbits(63)
    acquired = await runtime.scalar(
        text("SELECT pg_catalog.pg_try_advisory_xact_lock(:key)"), {"key": key}
    )
    if not acquired:
        raise TableRlsConfigurationError("Database identity check was busy; retry the operation")
    obtained = await other.scalar(
        text("SELECT pg_catalog.pg_try_advisory_xact_lock(:key)"), {"key": key}
    )
    if obtained:
        raise TableRlsConfigurationError(
            "Tables credentials must open separate connections to the same database"
        )


def policy_fingerprint(row: Mapping[str, object]) -> str:
    """Detect policy drift using stored expression trees, independent of search_path.

    This is operator metadata, not a signature against a database owner. The same
    owner who can replace a policy can replace its comment or disable RLS. A major
    PostgreSQL upgrade requires exact policy recreation before a new stamp is issued.
    """
    definition = [row[name] for name in ("qual", "check", "permissive", "cmd", "roles")]
    digest = hashlib.sha256(json.dumps(definition, separators=(",", ":")).encode()).hexdigest()
    major = int(str(row["server_version"])) // 10000
    return f"{POLICY_VERSION}.pg{major}:{digest}"


async def _policies(db: AsyncSession, objects: Sequence[str]) -> Sequence[RowMapping]:
    # asyncpg decodes PostgreSQL's internal "char" as bytes. Select text so the
    # runtime and the synchronous migration driver hash the same command tag.
    return (
        (
            await db.execute(
                text(
                    "SELECT c.relname AS tablename, p.polname AS policyname, "
                    "p.polpermissive AS permissive, p.polcmd::text AS cmd, p.polroles AS roles, "
                    "p.polqual::text AS qual, p.polwithcheck::text AS check, "
                    "pg_catalog.obj_description(p.oid, 'pg_policy') AS stamp, "
                    "pg_catalog.current_setting('server_version_num') AS server_version, "
                    "pg_catalog.pg_get_expr(p.polqual, p.polrelid) AS using_expression, "
                    "pg_catalog.pg_get_expr(p.polwithcheck, p.polrelid) AS check_expression "
                    "FROM pg_catalog.pg_policy AS p "
                    "JOIN pg_catalog.pg_class AS c ON c.oid = p.polrelid "
                    "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relname = ANY(:objects)"
                ),
                {"objects": list(objects)},
            )
        )
        .mappings()
        .all()
    )


async def require_table_policy_inventory(db: AsyncSession, *, recreate_owned: bool = False) -> None:
    state = await table_rls_state(db)
    # Also validates the all-or-none enforcement invariant before any DDL.
    _ = state.active
    missing = set(TABLE_OBJECTS) - state.present
    if missing:
        raise TableRlsConfigurationError(
            "Apply the complete Tables migration chain first: missing " + ", ".join(sorted(missing))
        )
    policies = await _policies(db, TABLE_OBJECTS)
    found = {(row["tablename"], row["policyname"]) for row in policies}
    expected = {
        (name, policy) for name in TABLE_OBJECTS for policy in (GUARD_POLICY, ACCESS_POLICY)
    }
    if found - expected or (not recreate_owned and found != expected):
        raise TableRlsConfigurationError(
            "Tables policy inventory differs from the installed migration; review it before activation"
        )
    if recreate_owned:
        # Only the explicit drained-services activation path reaches this. It
        # recreates every owned policy from exact SQL; it cannot stamp existing SQL.
        return
    for row in policies:
        permissive = row["policyname"] == ACCESS_POLICY
        if (
            row["permissive"] != permissive
            or row["cmd"] != "*"
            or row["roles"] != [0]
            or row["qual"] is None
            or row["check"] is None
            or row["stamp"] != policy_fingerprint(row)
            or (
                permissive
                and (row["using_expression"] != "true" or row["check_expression"] != "true")
            )
        ):
            raise TableRlsConfigurationError(
                "Tables policy definition changed; drain services and recreate the owned policies"
            )


async def install_table_policies(db: AsyncSession) -> None:
    """Install exact policy definitions; operator-only, under the migration connection.

    Activation recreates the two owned policies transactionally before enabling them,
    so a stale expression cannot survive an otherwise successful preflight. The
    restrictive guard cannot be widened by an additional permissive policy.
    """
    for name, tenant in TENANT_POLICIES.items():
        expression = f"({tenant}) OR ({MAINTENANCE_PREDICATE})"
        for policy in (GUARD_POLICY, ACCESS_POLICY):
            await db.execute(text(f'DROP POLICY IF EXISTS "{policy}" ON public."{name}"'))
        await db.execute(
            text(
                f'CREATE POLICY "{GUARD_POLICY}" ON public."{name}" AS RESTRICTIVE '
                f"FOR ALL TO PUBLIC USING ({expression}) WITH CHECK ({expression})"
            )
        )
        await db.execute(
            text(
                f'CREATE POLICY "{ACCESS_POLICY}" ON public."{name}" AS PERMISSIVE '
                "FOR ALL TO PUBLIC USING (true) WITH CHECK (true)"
            )
        )
        for row in await _policies(db, [name]):
            # Both identifiers come from the fixed inventory. The stamp contains
            # only a fixed version, a PostgreSQL major number and a hexadecimal hash.
            policy = str(row["policyname"])
            if policy in (GUARD_POLICY, ACCESS_POLICY):
                stamp = policy_fingerprint(row)
                await db.execute(
                    text(f'COMMENT ON POLICY "{policy}" ON public."{name}" IS \'{stamp}\'')
                )


async def preflight_table_rls(
    migration: AsyncSession,
    runtime: AsyncSession,
    maintenance: AsyncSession,
    *,
    recreate_owned: bool = False,
) -> None:
    """Read-only role/schema checks, plus transaction-local identity challenge locks."""
    await same_table_database(runtime, migration)
    await same_table_database(runtime, maintenance)
    runtime_role = await require_table_connection_role(runtime)
    maintenance_role = await require_table_connection_role(maintenance, maintenance=True)
    migration_role = str(await migration.scalar(text("SELECT current_user")))
    if migration_role in {runtime_role, maintenance_role}:
        raise TableRlsConfigurationError(
            "Migration, runtime and maintenance roles must be distinct"
        )
    owns_all = await migration.scalar(
        text(
            "SELECT bool_and(pg_catalog.pg_has_role(current_user, c.relowner, 'USAGE')) "
            "FROM pg_catalog.pg_class AS c "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname = ANY(:objects)"
        ),
        {"objects": list(TABLE_OBJECTS)},
    )
    if not owns_all:
        raise TableRlsConfigurationError(
            "Migration role must own the complete protected object set"
        )
    await require_table_policy_inventory(migration, recreate_owned=recreate_owned)
    await require_table_parent_integrity(maintenance)


async def require_table_parent_integrity(db: AsyncSession) -> None:
    """Report legacy corruption before policies could hide it; never repair data here.

    Preflight uses the separately verified maintenance connection so it can inspect
    all organizations even when repairing an already-active policy installation.
    """
    row = (
        await db.execute(
            text(
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
        )
    ).one()
    if row.triggers or row.admissions or row.grants:
        raise TableRlsConfigurationError(
            f"Tables legacy parent mismatch: triggers={row.triggers}, "
            f"admissions={row.admissions}, orphan_user_grants={row.grants}. "
            "Review these rows with the migration owner before retrying; no data was changed"
        )


async def activate_table_rls(
    migration: AsyncSession, runtime: AsyncSession, maintenance: AsyncSession
) -> None:
    """Verify three connections, then atomically enable and force the complete policy set.

    The operator has drained old API/worker versions before invoking this. There is no
    application setting that disables enforcement, and this function never edits roles
    or credentials.
    """
    await preflight_table_rls(migration, runtime, maintenance, recreate_owned=True)
    # The command owns fresh sessions. Release preflight's read locks before the
    # migration connection requests exclusive locks on the same objects.
    await maintenance.rollback()
    await migration.execute(text("SET LOCAL lock_timeout = '5s'"))
    await migration.execute(text("SET LOCAL statement_timeout = '30s'"))
    # Stabilize the whole object family before replacing policies or enabling enforcement.
    names = ", ".join(f'public."{name}"' for name in TABLE_OBJECTS)
    await migration.execute(text(f"LOCK TABLE {names} IN ACCESS EXCLUSIVE MODE"))
    await require_table_policy_inventory(migration, recreate_owned=True)
    await install_table_policies(migration)
    for name in TABLE_OBJECTS:
        await migration.execute(text(f'ALTER TABLE public."{name}" ENABLE ROW LEVEL SECURITY'))
        await migration.execute(text(f'ALTER TABLE public."{name}" FORCE ROW LEVEL SECURITY'))
