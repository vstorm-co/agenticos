"""Operator cutover refuses unsafe invocation and closes every owned connection."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from click.testing import CliRunner
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import NullPool

from app.commands import tables_rls as cmd
from app.db.table_rls import TableRlsConfigurationError, async_postgres_url, sync_postgres_url
from app.db.table_tenant import UnsafeTableDatabaseRoleError

pytestmark = [pytest.mark.anyio, pytest.mark.security]

MIGRATION_URL = "postgresql://migration:fixture-password@localhost/example"
RUNTIME_URL = "postgresql://runtime:fixture-password@localhost/example"
MAINTENANCE_URL = "postgresql://maintenance:fixture-password@localhost/example"


def test_migration_subprocess_uses_its_owned_database_instead_of_an_operator_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests import test_migrations

    monkeypatch.setenv(
        "POSTGRES_MIGRATION_URL",
        "postgresql://operator:fixture-password@external.invalid/operator_database",
    )
    monkeypatch.setattr(
        test_migrations,
        "settings",
        SimpleNamespace(
            DATABASE_URL_SYNC="postgresql://runtime:fixture-password@127.0.0.1:55437/application"
        ),
    )
    environment = test_migrations._env()
    selected = sync_postgres_url(environment["POSTGRES_MIGRATION_URL"])

    assert environment["POSTGRES_DB"] == test_migrations.MIGRATION_DATABASE
    assert selected.database == test_migrations.MIGRATION_DATABASE
    assert selected.host == "127.0.0.1"
    assert selected.port == 55437
    assert selected.username == "runtime"


@pytest.fixture
def connections(monkeypatch):
    configured = SimpleNamespace(
        POSTGRES_MIGRATION_URL=SecretStr(MIGRATION_URL),
        POSTGRES_MAINTENANCE_URL=SecretStr(MAINTENANCE_URL),
        DATABASE_URL=RUNTIME_URL,
    )
    sessions = [AsyncMock(spec=AsyncSession) for _ in range(3)]
    for session in sessions:
        session.__aenter__.return_value = session
    engines = [SimpleNamespace(dispose=AsyncMock()) for _ in range(3)]
    create = MagicMock(side_effect=engines)
    factories = [MagicMock(return_value=session) for session in sessions]
    maker = MagicMock(side_effect=factories)
    preflight = AsyncMock()
    activate = AsyncMock()
    monkeypatch.setattr(cmd, "settings", configured)
    monkeypatch.setattr(cmd, "create_async_engine", create)
    monkeypatch.setattr(cmd, "async_sessionmaker", maker)
    monkeypatch.setattr(cmd, "preflight_table_rls", preflight)
    monkeypatch.setattr(cmd, "activate_table_rls", activate)
    return SimpleNamespace(
        configured=configured,
        sessions=sessions,
        engines=engines,
        create=create,
        maker=maker,
        preflight=preflight,
        activate=activate,
    )


@pytest.mark.parametrize("activate", [False, True], ids=["preflight", "activate"])
async def test_operator_sessions_use_distinct_credentials_and_only_activation_commits(
    connections, activate
):
    await cmd._run(activate=activate)

    urls = (MIGRATION_URL, RUNTIME_URL, MAINTENANCE_URL)
    assert len(connections.create.call_args_list) == 3
    for invocation, url in zip(connections.create.call_args_list, urls, strict=True):
        assert invocation.args == (async_postgres_url(url),)
        assert invocation.kwargs == {
            "poolclass": NullPool,
            "connect_args": {"timeout": 10, "command_timeout": 30},
        }
    for invocation, engine in zip(
        connections.maker.call_args_list, connections.engines, strict=True
    ):
        assert invocation.args == (engine,)
    migration, runtime, maintenance = connections.sessions
    if activate:
        connections.activate.assert_awaited_once_with(migration, runtime, maintenance)
        connections.preflight.assert_not_awaited()
        migration.commit.assert_awaited_once()
    else:
        connections.preflight.assert_awaited_once_with(migration, runtime, maintenance)
        connections.activate.assert_not_awaited()
        migration.commit.assert_not_awaited()
    runtime.commit.assert_not_awaited()
    maintenance.commit.assert_not_awaited()
    for session, engine in zip(connections.sessions, connections.engines, strict=True):
        session.__aexit__.assert_awaited_once()
        engine.dispose.assert_awaited_once()


@pytest.mark.parametrize(
    "field",
    ["POSTGRES_MIGRATION_URL", "POSTGRES_MAINTENANCE_URL"],
    ids=["missing-migration", "missing-maintenance"],
)
async def test_missing_explicit_credentials_refuse_before_any_connection(connections, field):
    setattr(connections.configured, field, None)
    with pytest.raises(TableRlsConfigurationError, match="separate POSTGRES"):
        await cmd._run(activate=False)
    connections.create.assert_not_called()
    connections.preflight.assert_not_awaited()
    connections.activate.assert_not_awaited()


@pytest.mark.parametrize("activate", [False, True], ids=["preflight", "activate"])
async def test_a_failed_check_closes_all_sessions_without_committing(connections, activate):
    failure = TableRlsConfigurationError("The credentials name different databases")
    operation = connections.activate if activate else connections.preflight
    operation.side_effect = failure
    with pytest.raises(TableRlsConfigurationError, match="different databases"):
        await cmd._run(activate=activate)
    for session, engine in zip(connections.sessions, connections.engines, strict=True):
        session.commit.assert_not_awaited()
        session.__aexit__.assert_awaited_once()
        engine.dispose.assert_awaited_once()


async def test_partial_connection_setup_releases_already_created_resources(connections):
    connections.create.side_effect = [
        connections.engines[0],
        connections.engines[1],
        SQLAlchemyError("fixture connection failure"),
    ]
    with pytest.raises(SQLAlchemyError, match="fixture connection failure"):
        await cmd._run(activate=True)
    for session, engine in zip(connections.sessions[:2], connections.engines[:2], strict=True):
        session.__aexit__.assert_awaited_once()
        session.commit.assert_not_awaited()
        engine.dispose.assert_awaited_once()
    connections.engines[2].dispose.assert_not_awaited()
    connections.activate.assert_not_awaited()


async def test_a_failed_activation_commit_still_closes_every_resource(connections):
    connections.sessions[0].commit.side_effect = SQLAlchemyError("fixture commit failure")
    with pytest.raises(SQLAlchemyError, match="fixture commit failure"):
        await cmd._run(activate=True)
    connections.activate.assert_awaited_once()
    for session, engine in zip(connections.sessions, connections.engines, strict=True):
        session.__aexit__.assert_awaited_once()
        engine.dispose.assert_awaited_once()


@pytest.mark.parametrize(
    ("arguments", "activate", "message"),
    [
        ([], False, "Enforcement was not changed"),
        (["preflight"], False, "Enforcement was not changed"),
        (["activate", "--services-drained"], True, "enabled and forced"),
    ],
    ids=["default-preflight", "explicit-preflight", "drained-activation"],
)
def test_command_reports_the_selected_operation(monkeypatch, arguments, activate, message):
    run = AsyncMock()
    monkeypatch.setattr(cmd, "_run", run)
    result = CliRunner().invoke(cmd.tables_rls, arguments)
    assert result.exit_code == 0, result.output
    assert message in result.output
    run.assert_awaited_once_with(activate=activate)


def test_activation_requires_the_explicit_drained_services_attestation(monkeypatch):
    run = AsyncMock()
    monkeypatch.setattr(cmd, "_run", run)
    result = CliRunner().invoke(cmd.tables_rls, ["activate"])
    assert result.exit_code == 1
    assert "Drain API and worker processes first" in result.output
    run.assert_not_awaited()


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (TableRlsConfigurationError("Incomplete Tables policy inventory"), "Incomplete Tables"),
        (UnsafeTableDatabaseRoleError("Unsafe runtime role"), "Unsafe runtime role"),
    ],
    ids=["policy-configuration", "unsafe-role"],
)
def test_actionable_configuration_refusals_are_reported_without_success(
    monkeypatch, failure, message
):
    monkeypatch.setattr(cmd, "_run", AsyncMock(side_effect=failure))
    result = CliRunner().invoke(cmd.tables_rls, ["preflight"])
    assert result.exit_code == 1
    assert message in result.output
    assert "preflight passed" not in result.output


@pytest.mark.parametrize(
    "error_type", [SQLAlchemyError, OSError, TimeoutError], ids=["driver", "socket", "timeout"]
)
def test_database_errors_do_not_print_credentials_or_driver_details(monkeypatch, error_type):
    failure = error_type(f"Unable to connect with {MIGRATION_URL}")
    monkeypatch.setattr(cmd, "_run", AsyncMock(side_effect=failure))
    result = CliRunner().invoke(cmd.tables_rls, ["activate", "--services-drained"])
    assert result.exit_code == 1
    assert "Database preflight failed" in result.output
    assert "fixture-password" not in result.output
    assert MIGRATION_URL not in result.output
    assert "enabled and forced" not in result.output


@pytest.mark.parametrize(
    "value",
    [
        "fixture-password",
        "postgresql://user:fixture-password@localhost:invalid/example",
        "sqlite:///fixture-password.db",
    ],
    ids=["invalid-url", "invalid-port", "other-database"],
)
@pytest.mark.parametrize("convert", [async_postgres_url, sync_postgres_url], ids=["async", "sync"])
def test_invalid_credential_urls_have_a_safe_configuration_error(value, convert):
    with pytest.raises(TableRlsConfigurationError, match="PostgreSQL") as error:
        convert(value)
    assert "fixture-password" not in str(error.value)


def test_postgres_ssl_mode_is_preserved_for_the_async_driver():
    url = async_postgres_url(
        "postgresql://operator:fixture%40password@localhost/example?sslmode=require"
    )
    assert url.drivername == "postgresql+asyncpg"
    assert url.username == "operator"
    assert url.password == "fixture@password"
    assert url.query == {"ssl": "require"}


@pytest.mark.parametrize(
    ("scheme", "query", "expected_query"),
    [
        ("postgresql", "", {}),
        ("postgresql+asyncpg", "?ssl=verify-full", {"sslmode": "verify-full"}),
        ("postgresql+psycopg2", "?sslmode=require", {"sslmode": "require"}),
    ],
    ids=["provider-url", "async-url", "explicit-sync-url"],
)
def test_migration_urls_select_the_installed_sync_driver(scheme, query, expected_query):
    url = sync_postgres_url(f"{scheme}://operator:fixture%40password@localhost/example{query}")
    assert url.drivername == "postgresql+psycopg2"
    assert url.username == "operator"
    assert url.password == "fixture@password"
    assert url.query == expected_query
    assert "fixture@password" not in str(url)


@pytest.mark.parametrize(
    "query",
    [
        "ssl=require&sslmode=verify-full",
        "sslmode=require&sslmode=verify-full",
        "ssl=require&ssl=require",
        "sslrootcert=first.pem&sslrootcert=second.pem",
    ],
)
@pytest.mark.parametrize("convert", [async_postgres_url, sync_postgres_url], ids=["async", "sync"])
def test_tls_options_cannot_change_meaning_between_preflight_and_migration(query, convert):
    value = f"postgresql://operator:fixture-password@localhost/example?{query}"
    with pytest.raises(TableRlsConfigurationError, match="PostgreSQL") as error:
        convert(value)
    assert "fixture-password" not in str(error.value)


@pytest.mark.parametrize(
    ("convert", "key"),
    [(async_postgres_url, "ssl"), (sync_postgres_url, "sslmode")],
    ids=["async", "sync"],
)
def test_identical_tls_aliases_normalize_to_the_same_single_mode(convert, key):
    url = convert(
        "postgresql://operator@localhost/example?"
        "ssl=require&sslmode=require&application_name=table-preflight"
    )
    assert url.query == {key: "require", "application_name": "table-preflight"}
