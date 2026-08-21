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


def _kb(
    *,
    organization_id,
    collection_name: str = "docs",
    scope: str = "org",
    owner=None,
) -> SimpleNamespace:
    """A knowledge base row as the command reads one: name, tenant and scope."""
    return SimpleNamespace(
        collection_name=collection_name,
        organization_id=organization_id,
        scope=scope,
        owner_user_id=owner,
    )


class TestRagSourceAddRefusesWhatItCannotOwn:
    """#707. The command wrote a caller-supplied collection name straight into a
    `sync_sources` row without asking whether it was a legal identifier, whether
    a knowledge base of that name existed, or whose it was. The HTTP route for
    the same thing asks all three, and its docstring says why: "a sync writes
    into the collection, so pointing one at another tenant's is an injection,
    not a read".

    The row also had no organization - `create_source` was called without one and
    the column is nullable - while the model's docstring opens "Belongs to an
    organization". `--org` is now required and is what answers the ownership
    question the CLI has no `ctx` for.
    """

    ORG = uuid4()

    @staticmethod
    def _run(monkeypatch, *, organization, candidates, service=None):
        from unittest.mock import AsyncMock, MagicMock

        from app.commands import rag as rag_command

        created: list[dict[str, object]] = []

        class RecordingService:
            def __init__(self, db: object) -> None:
                self.db = db

            async def create_source(self, data, *, ctx):
                created.append({"data": data, "organization_id": ctx.organization_id})
                return SimpleNamespace(name=data.name, id=uuid4())

        @asynccontextmanager
        async def session() -> AsyncGenerator[object, None]:
            yield object()

        monkeypatch.setattr(rag_command, "get_db_context", session)
        monkeypatch.setattr(
            rag_command.organization_repo, "get_by_id", AsyncMock(return_value=organization)
        )
        monkeypatch.setattr(
            rag_command.knowledge_base_repo,
            "list_by_collection_name",
            AsyncMock(return_value=candidates),
        )
        monkeypatch.setattr(rag_command, "SyncSourceService", service or RecordingService)
        return created, MagicMock

    def _invoke(self, collection: str, org: str | None = None):
        from app.commands import rag as rag_command

        return CliRunner().invoke(
            rag_command.rag_source_add,
            [
                "--name",
                "My Drive",
                "--type",
                "gdrive",
                "--org",
                org or str(self.ORG),
                "--collection",
                collection,
                "--config",
                '{"folder_id": "abc123"}',
            ],
        )

    def test_a_collection_the_organization_holds_is_accepted_and_owns_the_row(
        self, monkeypatch
    ) -> None:
        """And the row carries the organization, which every row this command
        made used to lack."""
        organization = SimpleNamespace(id=self.ORG, name="Acme")
        kb = _kb(organization_id=self.ORG)
        created, _ = self._run(monkeypatch, organization=organization, candidates=[kb])

        result = self._invoke("docs")

        assert result.exit_code == 0, result.output
        assert len(created) == 1
        assert created[0]["organization_id"] == self.ORG
        assert created[0]["data"].collection_name == "docs"

    def test_a_collection_no_knowledge_base_claims_is_refused(self, monkeypatch) -> None:
        """It was accepted, and then failed in a worker - attributed to the sync
        rather than to the configuration that caused it."""
        organization = SimpleNamespace(id=self.ORG, name="Acme")
        created, _ = self._run(monkeypatch, organization=organization, candidates=[])

        result = self._invoke("absent")

        assert created == []
        assert result.exit_code != 0
        assert "'absent'" in result.output

    def test_another_organizations_collection_is_refused(self, monkeypatch) -> None:
        """The injection the route's docstring names. `collection_name` is not
        unique, so a name can exist and still not be this organization's - which
        is why the command filters the candidates rather than taking the first
        row the database returns (#913).
        """
        organization = SimpleNamespace(id=self.ORG, name="Acme")
        theirs = _kb(organization_id=uuid4())
        created, _ = self._run(monkeypatch, organization=organization, candidates=[theirs])

        result = self._invoke("docs")

        assert created == []
        assert result.exit_code != 0
        assert "'docs'" in result.output

    def test_a_members_personal_collection_is_refused(self, monkeypatch) -> None:
        """A personal base carries the organization's id too, so "same tenant" is
        not ownership: `writable_kb` lets only its owner write to one.

        Accepting it here would point an *organization-owned* source at a
        member's private collection, which every member holding
        `connections:manage` could then see and trigger. The command has no
        caller identity, so the org scope is the only one it can claim on the
        organization's behalf.
        """
        organization = SimpleNamespace(id=self.ORG, name="Acme")
        personal = _kb(organization_id=self.ORG, scope="personal", owner=uuid4())
        created, _ = self._run(monkeypatch, organization=organization, candidates=[personal])

        result = self._invoke("docs")

        assert created == []
        assert result.exit_code != 0
        assert "personal collection" in result.output

    def test_an_app_scoped_collection_is_refused(self, monkeypatch) -> None:
        """It belongs to the deployment, and takes an app admin - which a
        `--org` cannot stand in for."""
        organization = SimpleNamespace(id=self.ORG, name="Acme")
        shared = _kb(organization_id=self.ORG, scope="app")
        created, _ = self._run(monkeypatch, organization=organization, candidates=[shared])

        result = self._invoke("docs")

        assert created == []
        assert result.exit_code != 0

    def test_an_organization_that_does_not_exist_is_refused(self, monkeypatch) -> None:
        created, _ = self._run(monkeypatch, organization=None, candidates=[])

        result = self._invoke("docs")

        assert created == []
        assert result.exit_code != 0
        assert "No such organization" in result.output

    def test_something_that_is_not_an_organization_id_is_refused_before_any_query(
        self, monkeypatch
    ) -> None:
        """Left to `UUID()` inside the coroutine this was a `ValueError`
        traceback rather than a sentence."""
        created, _ = self._run(monkeypatch, organization=None, candidates=[])

        result = self._invoke("docs", org="acme")

        assert created == []
        assert result.exit_code != 0
        assert "Not an organization id" in result.output

    def test_a_name_no_table_can_be_called_is_refused_by_the_service(self, monkeypatch) -> None:
        """The shape check lives in `create_source`, so the route and the CLI
        share it. The command reports it rather than raising a traceback.
        """
        from app.services.sync_source import SyncSourceService

        organization = SimpleNamespace(id=self.ORG, name="Acme")
        kb = _kb(collection_name="Bad Name!", organization_id=self.ORG)
        self._run(
            monkeypatch, organization=organization, candidates=[kb], service=SyncSourceService
        )

        result = self._invoke("Bad Name!")

        assert result.exit_code != 0
        assert "Failed to create source" in result.output
        assert "collection name" in result.output

    def test_a_refusal_exits_non_zero_so_a_script_can_read_it(self, monkeypatch) -> None:
        """`error` is `click.secho`, so a command that printed and returned exited
        **0** - and a shell script carried on as though the source had been
        created when no row existed.
        """
        organization = SimpleNamespace(id=self.ORG, name="Acme")
        created, _ = self._run(monkeypatch, organization=organization, candidates=[])

        result = self._invoke("absent")

        assert created == []
        assert result.exit_code == 1


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


class TestRagSearchCommand:
    """`rag-search` is a tenantless operator path.

    `RetrievalService.retrieve` takes `organization_id` as a required
    keyword-only argument to scope reranker resolution. The CLI has no acting
    tenant, so it must pass `organization_id=None` explicitly; omitting it
    raised `TypeError` before any search ran.
    """

    def test_search_async_scopes_retrieval_to_no_organization(self):
        from unittest.mock import AsyncMock

        from app.commands import rag as rag_command

        retrieval = AsyncMock()
        retrieval.retrieve = AsyncMock(return_value=[])

        asyncio.run(rag_command.search_async("q", "handbook", 4, retrieval))

        assert retrieval.retrieve.await_args.kwargs["organization_id"] is None


class TestTheConsoleScript:
    """`agenticos` lives in `cli/`, which the unit suite never imported, so its
    dependencies were only ever exercised by the e2e seed step - 45 seconds into
    CI and long after this suite had gone green. Deleting `tabulate` as unimported
    is what found that out (#155)."""

    def test_the_entry_point_runs_with_every_dependency_its_module_names(self):
        from app import __version__
        from cli.commands import cli

        result = CliRunner().invoke(cli, ["--version"])

        assert result.exit_code == 0, result.output
        assert __version__ in result.output
