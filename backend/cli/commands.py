"""Project management CLI."""
# ruff: noqa: I001 - Imports structured for Jinja2 template conditionals

import asyncio

import click
import uvicorn
from alembic import command
from alembic.config import Config
from tabulate import tabulate

from app import __version__
from app.commands import register_commands
from app.main import app
from app.core.exceptions import AlreadyExistsError
from app.db.session import async_session_maker
from app.schemas.user import UserCreate
from app.services.user import UserService


@click.group()
@click.version_option(version=__version__, prog_name="agenticos")
def cli():
    """agenticos management CLI."""


@cli.group("server")
def server_cli():
    """Server commands."""


@server_cli.command("run")
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--port", default=8000, type=int, help="Port to bind to")
@click.option("--reload", is_flag=True, help="Enable auto-reload")
def server_run(host: str, port: int, reload: bool):
    """Run the development server."""
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
    )


@server_cli.command("routes")
def server_routes():
    """Show all registered routes."""
    routes = []
    for route in app.routes:
        if hasattr(route, "methods"):
            for method in route.methods - {"HEAD", "OPTIONS"}:
                routes.append([method, route.path, getattr(route, "name", "-")])

    click.echo(tabulate(routes, headers=["Method", "Path", "Name"]))


@cli.group("db")
def db_cli():
    """Database commands."""


@db_cli.command("init")
def db_init():
    """Initialize the database (run all migrations)."""
    click.echo("Initializing database...")
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    click.secho("Database initialized.", fg="green")


@db_cli.command("migrate")
@click.option("-m", "--message", required=True, help="Migration message")
def db_migrate(message: str):
    """Create a new migration."""
    alembic_cfg = Config("alembic.ini")
    command.revision(alembic_cfg, message=message, autogenerate=True)
    click.secho(f"Migration created: {message}", fg="green")


@db_cli.command("upgrade")
@click.option("--revision", default="head", help="Revision to upgrade to")
def db_upgrade(revision: str):
    """Run database migrations."""
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, revision)
    click.secho(f"Upgraded to: {revision}", fg="green")


@db_cli.command("downgrade")
@click.option("--revision", default="-1", help="Revision to downgrade to")
def db_downgrade(revision: str):
    """Rollback database migrations."""
    alembic_cfg = Config("alembic.ini")
    command.downgrade(alembic_cfg, revision)
    click.secho(f"Downgraded to: {revision}", fg="green")


@db_cli.command("current")
def db_current():
    """Show current migration revision."""
    alembic_cfg = Config("alembic.ini")
    command.current(alembic_cfg)


@db_cli.command("history")
def db_history():
    """Show migration history."""
    alembic_cfg = Config("alembic.ini")
    command.history(alembic_cfg)


@cli.group("user")
def user_cli():
    """User management commands."""


@user_cli.command("create")
@click.option("--email", prompt=True, help="User email")
@click.option(
    "--password", prompt=True, hide_input=True, confirmation_prompt=True, help="User password"
)
@click.option(
    "--superuser",
    is_flag=True,
    default=False,
    help="Also grant app-admin, which administers the whole deployment",
)
def user_create(email: str, password: str, superuser: bool):
    """Create a new user.

    There is no `--role`. A user's authority inside an organization is a
    membership row plus the permission catalog, granted from Users & Roles or
    `orgs`; the only privilege this command can hand out is the global one, and
    `--superuser` is it.
    """

    async def _create():
        async with async_session_maker() as session:
            user_service = UserService(session)
            try:
                user = await user_service.register(UserCreate(email=email, password=password))
                if superuser:
                    user.is_app_admin = True
                    session.add(user)
                await session.commit()
                return user
            except AlreadyExistsError:
                click.secho(f"User already exists: {email}", fg="red")
                return None

    user = asyncio.run(_create())
    if user:
        suffix = " (app admin)" if user.is_app_admin else ""
        click.secho(f"User created: {user.email}{suffix}", fg="green")


@user_cli.command("create-admin")
@click.option("--email", prompt=True, help="Admin email")
@click.option(
    "--password", prompt=True, hide_input=True, confirmation_prompt=True, help="Admin password"
)
def user_create_admin(email: str, password: str):
    """Create a user who administers the deployment.

    A shortcut for `user create --superuser`. Use it for the first account after
    setting up the database - though `agenticos cmd bootstrap` does this and
    rather more.
    """

    async def _create():
        async with async_session_maker() as session:
            user_service = UserService(session)
            try:
                user = await user_service.register(UserCreate(email=email, password=password))
                user.is_app_admin = True
                session.add(user)
                await session.commit()
                return user
            except AlreadyExistsError:
                click.secho(f"User already exists: {email}", fg="red")
                return None

    user = asyncio.run(_create())
    if user:
        click.secho(f"App admin created: {user.email}", fg="green")
        click.echo("This user administers the deployment and reaches every organization.")


@user_cli.command("list")
def user_list():
    """List all users."""

    async def _list():
        async with async_session_maker() as session:
            user_service = UserService(session)
            return await user_service.get_multi()

    users = asyncio.run(_list())

    if not users:
        click.echo("No users found.")
        return

    table = [[u.id, u.email, u.is_active, u.is_app_admin] for u in users]
    click.echo(tabulate(table, headers=["ID", "Email", "Active", "App admin"]))


@cli.group("cmd")
def cmd_cli():
    """Custom commands."""


register_commands(cmd_cli)


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
