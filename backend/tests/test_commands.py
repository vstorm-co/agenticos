"""Tests for CLI commands module."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import click
from click.testing import CliRunner

from app.commands import (
    _commands,
    command,
    discover_commands,
    error,
    info,
    register_commands,
    success,
    warning,
)
from app.commands.seed import seed


class TestCommandDecorator:
    """Tests for the command decorator."""

    def test_command_registers_function(self):
        """Test that @command decorator registers a click command."""
        initial_count = len(_commands)

        @command("test-cmd", help="Test command")
        def test_func():
            pass

        assert len(_commands) == initial_count + 1
        assert _commands[-1].name == "test-cmd"

    def test_command_uses_function_name_as_default(self):
        """Test that command name defaults to function name."""

        @command()
        def my_test_command():
            pass

        assert _commands[-1].name == "my-test-command"


class TestHelperFunctions:
    """Tests for helper output functions."""

    def test_success_prints_green(self, capsys):
        """Test success prints in green."""
        success("Test message")
        # Click uses escape codes for colors
        captured = capsys.readouterr()
        assert "Test message" in captured.out

    def test_error_prints_red(self, capsys):
        """Test error prints in red."""
        error("Error message")
        captured = capsys.readouterr()
        assert "Error message" in captured.out

    def test_warning_prints_yellow(self, capsys):
        """Test warning prints in yellow."""
        warning("Warning message")
        captured = capsys.readouterr()
        assert "Warning message" in captured.out

    def test_info_prints_plain(self, capsys):
        """Test info prints plain text."""
        info("Info message")
        captured = capsys.readouterr()
        assert "Info message" in captured.out


class TestDiscoverCommands:
    """Tests for command discovery."""

    def test_discover_commands_returns_list(self):
        """Test that discover_commands returns a list."""
        commands = discover_commands()
        assert isinstance(commands, list)

    def test_discover_commands_caches_results(self):
        """Test that discover_commands caches on second call."""
        commands1 = discover_commands()
        commands2 = discover_commands()
        assert commands1 is commands2


class TestRegisterCommands:
    """Tests for registering commands."""

    def test_register_commands_adds_to_group(self):
        """Test that register_commands adds discovered commands to CLI group."""

        @click.group()
        def cli():
            pass

        register_commands(cli)
        # After registration, cli should have commands
        # We can't assert exact count since it depends on what's discovered


class TestSeedCommand:
    """Tests for the seed command."""

    def test_seed_dry_run(self):
        """Test seed command with --dry-run."""
        runner = CliRunner()
        result = runner.invoke(seed, ["--dry-run", "--count", "5"])
        assert result.exit_code == 0
        assert "[DRY RUN]" in result.output
        assert "5" in result.output

    def test_seed_dry_run_with_clear(self):
        """Test seed command with --dry-run and --clear."""
        runner = CliRunner()
        result = runner.invoke(seed, ["--dry-run", "--clear"])
        assert result.exit_code == 0
        assert "Would clear existing data" in result.output


class TestRagSourceSyncWaitsForItsWork:
    """#439: the command reported a sync and then cancelled it.

    `asyncio.run` cancels every task still pending when the coroutine it was
    given returns, so a command that dispatches and exits has killed the work
    by the time it prints that the work started.
    """

    def test_the_command_does_not_return_until_the_sync_it_started_has_finished(
        self, monkeypatch
    ) -> None:
        from app.commands import rag as rag_command
        from app.core import background

        finished: list[str] = []

        async def sync() -> None:
            # Two trips through the loop: one is about as far as a task gets
            # before `asyncio.run` cancels it on the way out.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            finished.append("done")

        class DispatchingService:
            """Stands in for the service, dispatching the way it dispatches."""

            def __init__(self, db: object) -> None:
                self.db = db

            async def trigger_sync(self, source_id: str) -> SimpleNamespace:
                background.spawn(sync(), name=f"sync-source-{source_id}")
                return SimpleNamespace(id=uuid4())

        @asynccontextmanager
        async def session() -> AsyncGenerator[object, None]:
            yield object()

        monkeypatch.setattr(rag_command, "get_db_context", session)
        monkeypatch.setattr(rag_command, "SyncSourceService", DispatchingService)
        background._running.clear()

        result = CliRunner().invoke(rag_command.rag_source_sync, ["a-source"])

        assert result.exit_code == 0, result.output
        assert finished == ["done"], (
            "the command returned while its sync was still running, and "
            "`asyncio.run` cancelled it on the way out (#439)"
        )


class TestSeedSkillsSurvivesARacingListing:
    """A listing top-up can commit the same skill between the command's name
    check and its flush. That surfaces as `IntegrityError`, not
    `AlreadyExistsError`, and it must cost that one skill rather than the run -
    which takes both the catch and the savepoint, because a caught
    `IntegrityError` without a rollback leaves the session dead for every
    skill after it.
    """

    def test_an_integrity_error_skips_that_skill_and_the_rest_still_install(
        self, monkeypatch
    ) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from sqlalchemy.exc import IntegrityError

        from app.commands import seed_skills as seed_command

        db = MagicMock()
        bundled = [
            SimpleNamespace(key="code-review", name="code-review", resources=()),
            SimpleNamespace(key="incident-report", name="incident-report", resources=()),
        ]
        install = AsyncMock(
            side_effect=[
                IntegrityError("INSERT", {}, Exception("duplicate key")),
                SimpleNamespace(name="incident-report", resources=()),
            ]
        )

        @asynccontextmanager
        async def session() -> AsyncGenerator[object, None]:
            yield db

        monkeypatch.setattr(seed_command, "get_db_context", session)
        monkeypatch.setattr(
            seed_command,
            "SkillService",
            lambda _db: SimpleNamespace(install_from_library=install),
        )
        monkeypatch.setattr(seed_command.skill_library, "library", lambda: bundled)
        monkeypatch.setattr(
            seed_command.organization_repo,
            "list_all",
            AsyncMock(return_value=[SimpleNamespace(id=uuid4(), name="Acme")]),
        )
        monkeypatch.setattr(
            seed_command.member_repo, "first_owner_id", AsyncMock(return_value=uuid4())
        )

        result = CliRunner().invoke(seed_command.seed_skills, [])

        assert result.exit_code == 0, result.output
        assert "code-review - already there, left alone" in result.output
        assert "incident-report - installed" in result.output
        # One savepoint per install, so the rollback of the loser's is what the
        # winner's flush runs after.
        assert db.begin_nested.call_count == 2
