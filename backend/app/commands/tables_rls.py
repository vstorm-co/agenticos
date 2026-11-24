"""Preflight or activate the complete Tables tenant RLS policy family."""

import asyncio
from contextlib import AsyncExitStack

import click
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.commands import command
from app.core.config import settings
from app.db.table_rls import (
    TableRlsConfigurationError,
    activate_table_rls,
    async_postgres_url,
    preflight_table_rls,
)
from app.db.table_tenant import UnsafeTableDatabaseRoleError


async def _run(*, activate: bool) -> None:
    migration_url = settings.POSTGRES_MIGRATION_URL
    maintenance_url = settings.POSTGRES_MAINTENANCE_URL
    if migration_url is None or maintenance_url is None:
        raise TableRlsConfigurationError(
            "Set separate POSTGRES_MIGRATION_URL and POSTGRES_MAINTENANCE_URL credentials first"
        )
    async with AsyncExitStack() as stack:
        sessions = []
        for url in (
            migration_url.get_secret_value(),
            settings.DATABASE_URL,
            maintenance_url.get_secret_value(),
        ):
            engine = create_async_engine(
                async_postgres_url(url),
                poolclass=NullPool,
                connect_args={"timeout": 10, "command_timeout": 30},
            )
            stack.push_async_callback(engine.dispose)
            session = await stack.enter_async_context(async_sessionmaker(engine)())
            sessions.append(session)
        migration, runtime, maintenance = sessions
        if activate:
            await activate_table_rls(migration, runtime, maintenance)
            await migration.commit()
        else:
            await preflight_table_rls(migration, runtime, maintenance)


@command("tables-rls")
@click.argument("operation", type=click.Choice(["preflight", "activate"]), default="preflight")
@click.option(
    "--services-drained",
    is_flag=True,
    help="Confirm old API and worker processes have been drained and will restart on this version.",
)
def tables_rls(operation: str, services_drained: bool) -> None:
    """Verify credentials and policies, then optionally enable database enforcement.

    This never provisions or changes credentials. Run with the deployment's runtime
    settings plus the explicitly supplied migration and maintenance DSNs.
    """
    if operation == "activate" and not services_drained:
        raise click.ClickException(
            "Drain API and worker processes first, then pass --services-drained"
        )
    try:
        asyncio.run(_run(activate=operation == "activate"))
    except (TableRlsConfigurationError, UnsafeTableDatabaseRoleError) as exc:
        raise click.ClickException(str(exc)) from None
    except SQLAlchemyError, OSError, TimeoutError:
        raise click.ClickException(
            "Database preflight failed; check connectivity, migration privileges and lock availability"
        ) from None
    click.echo(
        "Tables tenant RLS is enabled and forced on the complete policy family."
        if operation == "activate"
        else "Tables RLS preflight passed. Enforcement was not changed."
    )
