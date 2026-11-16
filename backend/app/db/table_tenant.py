"""Transaction-local tenant context for the staged Tables RLS rollout.

Only a trusted server AuthContext may supply this value. It is a database
backstop for omitted tenant predicates, not a substitute for table/row access
checks or an authorization mechanism for untrusted SQL clients.

This foundation does not enable policies on production tables. Every entry
point, including workers, must bind a context before enforcement is activated.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, AsyncSessionTransaction

if TYPE_CHECKING:
    from app.core.permissions import AuthContext


ORGANIZATION_POLICY = (
    "organization_id = NULLIF(current_setting('t3os.organization_id', true), '')::uuid"
)
"""Use for both USING and WITH CHECK; an unset/reset setting matches no row."""

_SESSION_KEY = "t3os_table_tenant"


class TableTenantContextError(RuntimeError):
    """A caller tried to change tenant or bind only inside a savepoint."""


class UnsafeTableDatabaseRoleError(RuntimeError):
    """The runtime role bypasses PostgreSQL row-level security unconditionally."""


@dataclass(frozen=True)
class _BoundTenant:
    transaction: AsyncSessionTransaction
    organization_id: UUID


async def bind_table_tenant(db: AsyncSession, ctx: AuthContext) -> None:
    """Bind one authenticated tenant until the current outer transaction ends.

    Repeated calls for the same tenant cost no query. A different tenant in the
    same transaction is a programming error: start another transaction instead.
    The transaction identity, rather than the session or connection identity,
    lets a reused session bind a new tenant after commit or rollback.

    A first binding inside a savepoint is refused because rolling back that
    savepoint would undo SET LOCAL while leaving the Python outer-transaction
    marker alive. An already-bound outer context remains usable in savepoints.
    No transaction is committed here, and no session-wide SET is used.
    """
    transaction = db.get_transaction()
    bound = db.info.get(_SESSION_KEY)
    if isinstance(bound, _BoundTenant) and bound.transaction is transaction:
        if bound.organization_id != ctx.organization_id:
            raise TableTenantContextError("Cannot switch table tenant within one transaction")
        return
    if db.in_nested_transaction():
        raise TableTenantContextError("Bind the table tenant before opening a savepoint")
    if transaction is None:
        transaction = await db.begin()
    # A pending ORM write must not flush before PostgreSQL has the tenant value.
    with db.no_autoflush:
        await db.execute(
            text("SELECT set_config('t3os.organization_id', :organization_id, true)"),
            {"organization_id": str(ctx.organization_id)},
        )
    db.info[_SESSION_KEY] = _BoundTenant(transaction, ctx.organization_id)


async def require_non_bypass_table_role(db: AsyncSession) -> None:
    """Refuse superuser/BYPASSRLS credentials on a runtime connection.

    Run this on the application pool, not the migration connection. Table
    ownership, policy coverage and ENABLE/FORCE state are separate rollout
    checks; passing this check alone does not prove enforcement is active.
    """
    result = await db.execute(
        text("SELECT rolsuper, rolbypassrls FROM pg_catalog.pg_roles WHERE rolname = current_user")
    )
    role = result.one()
    if role.rolsuper or role.rolbypassrls:
        raise UnsafeTableDatabaseRoleError(
            "Tables RLS requires a runtime role without SUPERUSER or BYPASSRLS"
        )
