"""The workspace an agent works in: who shares it, and what it refuses.

Most of this platform's value is in what it refuses, and a workspace has three
refusals worth more than the feature itself:

* a run in one organization cannot reach another organization's files;
* a scope the run cannot key is refused by name rather than falling back to a
  broader one, because the fallback would merge strangers' workspaces silently;
* a write past the storage ceiling is rejected with a message the model reads,
  rather than accepted and dropped in a `finally` block.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai_backends import StateBackend

from app.agents.capabilities import build as build_capabilities
from app.agents.capabilities import get as get_capability
from app.agents.capabilities._registry import CapabilityBinding
from app.agents.capabilities.approval import approval_required_tools
from app.agents.capabilities.sandbox import SandboxConfig
from app.agents.capabilities.sandbox._capped import CappedStateBackend, document_size
from app.agents.capabilities.sandbox._identity import (
    MAX_SESSION_ID,
    WorkspaceIdentity,
    WorkspaceScopeUnavailable,
    scope_key,
)
from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError
from app.repositories import agent_workspace as workspace_repo
from app.services.sandbox_workspace import SandboxWorkspaceService, sandbox_config

pytestmark = pytest.mark.anyio


def _identity(**overrides: object) -> WorkspaceIdentity:
    defaults: dict[str, object] = {
        "organization_id": uuid4(),
        "agent_id": uuid4(),
        "run_id": uuid4(),
        "conversation_id": uuid4(),
        "user_id": "user-1",
    }
    return WorkspaceIdentity(**{**defaults, **overrides})  # type: ignore[arg-type]


def _spec(**config: object) -> AgentSpec:
    return AgentSpec(
        name="Analyst",
        capabilities=[{"id": "sandbox", "config": config}],
    )


def _daytona_spec() -> tuple[AgentSpec, dict]:
    """A spec whose workspace names a key, and the unsealed key itself.

    Daytona is the one backend that authenticates, and it authenticates to an
    account the *organization* pays for - so the key has to come from the
    organization's vault. The SDK's own `DAYTONA_API_KEY` fallback would put
    every tenant's sandboxes on whichever account the deployment configured.
    """
    from app.core.secret_kinds import ApiKeySecret

    secret_id = uuid4()
    spec = AgentSpec(
        name="Analyst",
        capabilities=[
            {"id": "sandbox", "config": {"backend": "daytona"}, "secret_id": str(secret_id)}
        ],
    )
    return spec, {secret_id: ApiKeySecret(api_key="dtn-live-key")}


class TestWhoSharesAWorkspace:
    def test_two_organizations_never_share_a_key(self):
        """The refusal this whole feature is measured against."""
        conversation = uuid4()
        agent = uuid4()
        first = _identity(organization_id=uuid4(), agent_id=agent, conversation_id=conversation)
        second = _identity(organization_id=uuid4(), agent_id=agent, conversation_id=conversation)

        assert scope_key(first, "conversation", "state") != scope_key(
            second, "conversation", "state"
        )

    def test_the_same_conversation_returns_to_the_same_workspace(self):
        identity = _identity()

        assert scope_key(identity, "conversation", "state") == scope_key(
            _identity(
                organization_id=identity.organization_id,
                agent_id=identity.agent_id,
                conversation_id=identity.conversation_id,
                run_id=uuid4(),
            ),
            "conversation",
            "state",
        )

    def test_a_run_scoped_workspace_is_new_every_turn(self):
        identity = _identity()
        next_turn = _identity(
            organization_id=identity.organization_id,
            agent_id=identity.agent_id,
            conversation_id=identity.conversation_id,
        )

        assert scope_key(identity, "run", "state") != scope_key(next_turn, "run", "state")

    def test_a_user_workspace_is_per_agent(self):
        """Files gathered for one agent are not another agent's to read."""
        organization = uuid4()
        first = _identity(organization_id=organization, agent_id=uuid4())
        second = _identity(organization_id=organization, agent_id=uuid4())

        assert scope_key(first, "user", "state") != scope_key(second, "user", "state")

    def test_two_user_ids_differing_only_in_punctuation_do_not_collide(self):
        """Sanitising instead of hashing mapped `a.b` and `ab` onto one workspace."""
        agent, organization = uuid4(), uuid4()
        dotted = _identity(organization_id=organization, agent_id=agent, user_id="a.b")
        plain = _identity(organization_id=organization, agent_id=agent, user_id="ab")

        assert scope_key(dotted, "user", "state") != scope_key(plain, "user", "state")

    def test_changing_the_backend_does_not_reattach_to_the_old_workspace(self):
        """A stored document and a container's volume are not the same thing."""
        identity = _identity()

        assert scope_key(identity, "conversation", "state") != scope_key(
            identity, "conversation", "docker"
        )

    @pytest.mark.parametrize("scope", ["run", "conversation", "user", "agent"])
    def test_every_key_fits_what_the_service_accepts(self, scope: str):
        """`sandboxd` rejects an id over 64 characters, on the first tool call."""
        identity = _identity(user_id="U" * 200)

        assert len(scope_key(identity, scope, "docker")) <= MAX_SESSION_ID  # type: ignore[arg-type]

    def test_a_conversation_scope_with_no_conversation_is_refused(self):
        with pytest.raises(WorkspaceScopeUnavailable):
            scope_key(_identity(conversation_id=None), "conversation", "state")

    def test_a_user_scope_with_no_user_is_refused(self):
        """Rather than falling back and merging strangers' files."""
        with pytest.raises(WorkspaceScopeUnavailable):
            scope_key(_identity(user_id=None), "user", "state")


class TestTheStorageCeiling:
    def test_a_write_past_the_ceiling_is_refused_and_rolled_back(self):
        backend = CappedStateBackend(StateBackend(), max_bytes=400)
        backend.write("/keep.txt", "hello")

        result = backend.write("/huge.txt", "x" * 5000)

        assert result.error is not None
        assert "workspace is full" in result.error
        assert backend.exists("/keep.txt")
        assert not backend.exists("/huge.txt")

    def test_an_edit_past_the_ceiling_leaves_the_file_as_it_was(self):
        backend = CappedStateBackend(StateBackend(), max_bytes=400)
        backend.write("/notes.txt", "hello")

        result = backend.edit("/notes.txt", "hello", "y" * 5000)

        assert result.error is not None
        assert "hello" in backend.read("/notes.txt")

    def test_an_edit_inside_the_ceiling_goes_through(self):
        backend = CappedStateBackend(StateBackend(), max_bytes=4096)
        backend.write("/notes.txt", "hello world")

        result = backend.edit("/notes.txt", "world", "there")

        assert result.error is None
        assert result.occurrences == 1
        assert "hello there" in backend.read("/notes.txt")

    def test_a_failing_write_is_reported_rather_than_measured(self):
        """A path the backend rejects never reaches the ceiling check."""
        backend = CappedStateBackend(StateBackend(), max_bytes=400)

        result = backend.write("../escape.txt", "x")

        assert result.error is not None
        assert "workspace is full" not in result.error

    def test_an_edit_of_a_missing_file_is_reported_unchanged(self):
        backend = CappedStateBackend(StateBackend(), max_bytes=400)

        result = backend.edit("/nothing.txt", "a", "b")

        assert result.error is not None
        assert "not found" in result.error

    def test_the_read_side_is_delegated_untouched(self):
        backend = CappedStateBackend(StateBackend(), max_bytes=4096)
        backend.write("/src/app.py", "print('hi')\nprint('there')")

        assert backend.exists("/src/app.py")
        assert [entry["name"] for entry in backend.ls_info("/src")] == ["app.py"]
        assert backend.read_bytes("/src/app.py").startswith(b"print")
        assert "print" in backend.read("/src/app.py")
        assert [entry["name"] for entry in backend.glob_info("**/*.py")] == ["app.py"]
        assert backend.grep_raw("there")
        assert "CappedStateBackend" in repr(backend)

    def test_size_is_measured_as_the_document_that_gets_stored(self):
        backend = StateBackend()
        backend.write("/a.txt", "x")

        assert document_size(backend.files) > 0


class TestReadingTheSpec:
    def test_an_agent_without_the_capability_has_no_workspace(self):
        assert sandbox_config(AgentSpec(name="Plain")) is None

    def test_a_disabled_binding_is_no_workspace(self):
        spec = AgentSpec(
            name="Off", capabilities=[{"id": "sandbox", "config": {}, "enabled": False}]
        )

        assert sandbox_config(spec) is None

    def test_the_defaults_are_the_ones_every_deployment_can_run(self):
        config = sandbox_config(_spec())

        assert config == SandboxConfig(backend="state", session_scope="conversation")


class TestApprovalIsPerTool:
    def test_reading_is_free_and_writing_is_gated(self):
        """One flag for the capability would gate `ls`, and authors would turn
        the lot off rather than write seven overrides."""
        gated = approval_required_tools(_spec())

        assert "write_file" in gated
        assert "execute" in gated
        assert "read_file" not in gated
        assert "ls" not in gated

    def test_a_binding_still_overrides_the_code(self):
        spec = AgentSpec(
            name="Careful",
            capabilities=[
                {"id": "sandbox", "config": {}, "tool_approval": {"read_file": "required"}}
            ],
        )

        assert "read_file" in approval_required_tools(spec)

    def test_renaming_a_tool_keeps_its_gate(self):
        """The failure this is guarding: a renamed `execute` running unattended."""
        spec = AgentSpec(
            name="Renamed",
            capabilities=[
                {"id": "sandbox", "config": {}, "tool_overrides": {"execute": {"name": "run_it"}}}
            ],
        )

        gated = approval_required_tools(spec)

        assert "run_it" in gated
        assert "execute" not in gated


class TestBuildingTheCapability:
    def test_without_a_backend_the_workspace_is_in_memory(self):
        """A preview has nowhere durable to write, which is not an error."""
        built = build_capabilities([CapabilityBinding(capability_id="sandbox")])

        toolset = built[0].get_toolset()

        assert toolset is not None
        assert "write_file" in toolset.tools

    def test_turning_the_shell_off_removes_it_rather_than_gating_it(self):
        built = build_capabilities(
            [CapabilityBinding(capability_id="sandbox", config={"include_execute": False})]
        )

        toolset = built[0].get_toolset()

        assert toolset is not None
        assert "execute" not in toolset.tools

    def test_the_catalog_and_the_model_read_the_same_description(self):
        """Two copies in two repositories drift, and nothing reports it."""
        definition = get_capability("sandbox")
        built = build_capabilities([CapabilityBinding(capability_id="sandbox")])
        toolset = built[0].get_toolset()

        assert toolset is not None
        for tool in definition.tools:
            assert toolset.tools[tool.id].tool_def.description == tool.description

    def test_the_background_shells_are_not_offered(self):
        built = build_capabilities([CapabilityBinding(capability_id="sandbox")])
        toolset = built[0].get_toolset()

        assert toolset is not None
        assert "run_in_background" not in toolset.tools

    def test_a_secret_is_only_demanded_by_the_backend_that_authenticates(self):
        definition = get_capability("sandbox")

        assert not definition.needs_secret(SandboxConfig(backend="state"))
        assert not definition.needs_secret(SandboxConfig(backend="docker"))
        assert definition.needs_secret(SandboxConfig(backend="daytona"))


class TestOpeningAndClosing:
    async def test_an_agent_without_a_workspace_opens_nothing(self, mock_db_session):
        service = SandboxWorkspaceService(mock_db_session)

        assert await service.open(AgentSpec(name="Plain"), identity=_identity()) is None

    async def test_a_run_scoped_state_workspace_needs_no_row(self, monkeypatch, mock_db_session):
        created = AsyncMock()
        monkeypatch.setattr(workspace_repo, "create", created)
        service = SandboxWorkspaceService(mock_db_session)

        workspace = await service.open(_spec(session_scope="run"), identity=_identity())

        assert workspace is not None
        assert workspace.row_id is None
        created.assert_not_called()

    async def test_a_stored_document_comes_back_on_the_next_turn(
        self, monkeypatch, mock_db_session
    ):
        stored = StateBackend()
        stored.write("/report.md", "the numbers")
        row = _row(files=dict(stored.files))
        monkeypatch.setattr(workspace_repo, "get_by_key", AsyncMock(return_value=row))
        monkeypatch.setattr(workspace_repo, "touch", AsyncMock(return_value=row))
        service = SandboxWorkspaceService(mock_db_session)

        workspace = await service.open(_spec(), identity=_identity())

        assert workspace is not None
        assert "the numbers" in workspace.backend.read("/report.md")

    async def test_closing_stores_what_the_run_wrote(self, monkeypatch, mock_db_session):
        row = _row()
        monkeypatch.setattr(workspace_repo, "get_by_key", AsyncMock(return_value=None))
        monkeypatch.setattr(workspace_repo, "create", AsyncMock(return_value=row))
        saved = AsyncMock(return_value=row)
        monkeypatch.setattr(workspace_repo, "save_files", saved)
        mock_db_session.get = AsyncMock(return_value=row)
        service = SandboxWorkspaceService(mock_db_session)

        workspace = await service.open(_spec(), identity=_identity())
        assert workspace is not None
        workspace.backend.write("/notes.txt", "kept")
        await service.close(workspace)

        assert "/notes.txt" in saved.await_args.kwargs["files"]
        assert saved.await_args.kwargs["bytes_total"] > 0

    async def test_closing_nothing_is_not_an_error(self, mock_db_session):
        await SandboxWorkspaceService(mock_db_session).close(None)

    async def test_a_run_scoped_state_workspace_is_not_stored(self, monkeypatch, mock_db_session):
        """It has no row by design, so there is nowhere for it to persist to -
        which is exactly what "a fresh workspace every turn" means."""
        saved = AsyncMock()
        monkeypatch.setattr(workspace_repo, "save_files", saved)
        service = SandboxWorkspaceService(mock_db_session)

        workspace = await service.open(_spec(session_scope="run"), identity=_identity())
        assert workspace is not None
        workspace.backend.write("/scratch.txt", "gone after this")
        await service.close(workspace)

        saved.assert_not_called()

    async def test_a_conversation_deleted_mid_run_loses_its_files(
        self, monkeypatch, mock_db_session
    ):
        """The files belonged to it; keeping them would outlive the thread."""
        row = _row()
        monkeypatch.setattr(workspace_repo, "get_by_key", AsyncMock(return_value=None))
        monkeypatch.setattr(workspace_repo, "create", AsyncMock(return_value=row))
        saved = AsyncMock()
        monkeypatch.setattr(workspace_repo, "save_files", saved)
        mock_db_session.get = AsyncMock(return_value=None)
        service = SandboxWorkspaceService(mock_db_session)

        workspace = await service.open(_spec(), identity=_identity())
        await service.close(workspace)

        saved.assert_not_called()

    async def test_a_storage_failure_does_not_replace_the_run_s_own_outcome(
        self, monkeypatch, mock_db_session
    ):
        """`close` runs in the same `finally` that records what the run cost."""
        row = _row()
        monkeypatch.setattr(workspace_repo, "get_by_key", AsyncMock(return_value=None))
        monkeypatch.setattr(workspace_repo, "create", AsyncMock(return_value=row))
        monkeypatch.setattr(
            workspace_repo, "save_files", AsyncMock(side_effect=RuntimeError("database gone"))
        )
        mock_db_session.get = AsyncMock(return_value=row)
        service = SandboxWorkspaceService(mock_db_session)

        workspace = await service.open(_spec(), identity=_identity())

        await service.close(workspace)

    async def test_a_scope_this_run_cannot_key_is_refused_by_name(self, mock_db_session):
        service = SandboxWorkspaceService(mock_db_session)

        with pytest.raises(BadRequestError) as exc:
            await service.open(_spec(session_scope="user"), identity=_identity(user_id=None))

        assert "no signed-in user" in exc.value.message

    async def test_a_container_backend_without_a_service_is_refused(
        self, monkeypatch, mock_db_session
    ):
        from app.core import config as config_module

        monkeypatch.setattr(config_module.settings, "SANDBOXD_URL", "")
        service = SandboxWorkspaceService(mock_db_session)

        with pytest.raises(BadRequestError) as exc:
            await service.open(_spec(backend="docker"), identity=_identity())

        assert exc.value.details["setting"] == "SANDBOXD_URL"


def _row(**overrides: object):
    from app.db.models.agent_workspace import AgentWorkspace

    row = AgentWorkspace(
        id=uuid4(),
        organization_id=uuid4(),
        agent_id=uuid4(),
        scope="conversation",
        scope_key="sc-deadbeef-cafe",
        backend="state",
        files=None,
        bytes_total=0,
        version=0,
    )
    for name, value in overrides.items():
        setattr(row, name, value)
    return row


class TestContainerBackedWorkspaces:
    """The paths that talk to something outside this process."""

    async def test_a_docker_workspace_labels_its_tenant_and_reattaches(
        self, monkeypatch, mock_db_session
    ):
        """`tenant` is capacity accounting, and `reuse` is what makes a
        conversation's workspace the same one next turn rather than a 409."""
        from pydantic_ai_backends import remote as remote_module

        from app.core import config as config_module

        monkeypatch.setattr(config_module.settings, "SANDBOXD_URL", "http://sandboxd:8080")
        monkeypatch.setattr(config_module.settings, "SANDBOXD_TOKEN", "service-token")
        seen: dict[str, object] = {}

        class _Sandbox:
            def __init__(self, url, **kwargs):
                seen.update(kwargs, url=url)

        monkeypatch.setattr(remote_module, "RemoteSandbox", _Sandbox)
        row = _row(backend="docker")
        monkeypatch.setattr(workspace_repo, "get_by_key", AsyncMock(return_value=None))
        created = AsyncMock(return_value=row)
        monkeypatch.setattr(workspace_repo, "create", created)
        identity = _identity()

        workspace = await SandboxWorkspaceService(mock_db_session).open(
            _spec(backend="docker", runtime="python"), identity=identity
        )

        assert workspace is not None
        assert workspace.kind == "docker"
        assert seen["tenant"] == str(identity.organization_id)
        assert seen["reuse"] is True
        assert seen["runtime"] == "python"
        # The service is told which session belongs to this row, so deleting the
        # conversation can purge the sandbox rather than wait for a TTL.
        assert created.await_args.kwargs["session_id"] == workspace.scope_key

    async def test_a_daytona_workspace_uses_the_organizations_own_key(
        self, monkeypatch, mock_db_session
    ):
        import pydantic_ai_backends as backends_module

        seen: dict[str, object] = {}

        class _Sandbox:
            def __init__(self, api_key=None, sandbox_id=None):
                seen.update(api_key=api_key, sandbox_id=sandbox_id)

        monkeypatch.setattr(backends_module, "DaytonaSandbox", _Sandbox, raising=False)
        monkeypatch.setattr(workspace_repo, "get_by_key", AsyncMock(return_value=None))
        monkeypatch.setattr(
            workspace_repo, "create", AsyncMock(return_value=_row(backend="daytona"))
        )
        spec, secrets = _daytona_spec()

        workspace = await SandboxWorkspaceService(mock_db_session).open(
            spec, identity=_identity(), secrets=secrets
        )

        assert workspace is not None
        assert seen["api_key"] == "dtn-live-key"
        assert seen["sandbox_id"] == workspace.scope_key

    async def test_a_key_belonging_to_another_capability_is_not_mistaken_for_this_one(
        self, monkeypatch, mock_db_session
    ):
        """An agent can hold several secrets - a search key and a Daytona key -
        and picking the wrong one would authenticate a sandbox with a Tavily
        token and fail somewhere unhelpful."""
        from pydantic_ai_backends import remote as remote_module

        from app.core import config as config_module
        from app.core.secret_kinds import ApiKeySecret

        monkeypatch.setattr(config_module.settings, "SANDBOXD_URL", "http://sandboxd:8080")
        monkeypatch.setattr(remote_module, "RemoteSandbox", lambda url, **kwargs: object())
        monkeypatch.setattr(workspace_repo, "get_by_key", AsyncMock(return_value=None))
        monkeypatch.setattr(
            workspace_repo, "create", AsyncMock(return_value=_row(backend="docker"))
        )
        elsewhere = uuid4()
        spec = AgentSpec(
            name="Analyst",
            capabilities=[
                {"id": "sandbox", "config": {"backend": "docker"}},
                {"id": "web_research", "config": {"method": "tavily"}, "secret_id": str(elsewhere)},
            ],
        )

        workspace = await SandboxWorkspaceService(mock_db_session).open(
            spec,
            identity=_identity(),
            secrets={elsewhere: ApiKeySecret(api_key="tvly-key")},
        )

        assert workspace is not None
        assert workspace.kind == "docker"

    async def test_a_daytona_workspace_whose_key_was_deleted_is_refused(self, mock_db_session):
        """Rather than falling through to the SDK's environment variable, which
        would bill this organization's sandboxes to somebody else's account."""
        spec, _ = _daytona_spec()

        with pytest.raises(BadRequestError) as exc:
            await SandboxWorkspaceService(mock_db_session).open(spec, identity=_identity())

        assert "Daytona key" in exc.value.message

    async def test_a_run_scoped_sandbox_is_released_when_the_run_ends(
        self, monkeypatch, mock_db_session
    ):
        from pydantic_ai_backends import remote as remote_module

        from app.core import config as config_module

        monkeypatch.setattr(config_module.settings, "SANDBOXD_URL", "http://sandboxd:8080")
        stopped: dict[str, object] = {}

        class _Sandbox:
            def __init__(self, url, **kwargs):
                pass

            def stop(self, purge=False):
                stopped["purge"] = purge

        monkeypatch.setattr(remote_module, "RemoteSandbox", _Sandbox)
        service = SandboxWorkspaceService(mock_db_session)

        workspace = await service.open(
            _spec(backend="docker", session_scope="run"), identity=_identity()
        )
        await service.close(workspace)

        assert stopped == {"purge": True}

    async def test_a_conversation_scoped_sandbox_outlives_the_run(
        self, monkeypatch, mock_db_session
    ):
        """The next turn is meant to find the files this one wrote."""
        from pydantic_ai_backends import remote as remote_module

        from app.core import config as config_module

        monkeypatch.setattr(config_module.settings, "SANDBOXD_URL", "http://sandboxd:8080")
        stopped: list[bool] = []

        class _Sandbox:
            def __init__(self, url, **kwargs):
                pass

            def stop(self, purge=False):
                stopped.append(purge)

        monkeypatch.setattr(remote_module, "RemoteSandbox", _Sandbox)
        monkeypatch.setattr(workspace_repo, "get_by_key", AsyncMock(return_value=None))
        monkeypatch.setattr(
            workspace_repo, "create", AsyncMock(return_value=_row(backend="docker"))
        )
        service = SandboxWorkspaceService(mock_db_session)

        workspace = await service.open(_spec(backend="docker"), identity=_identity())
        await service.close(workspace)

        assert stopped == []

    async def test_a_backend_that_cannot_be_stopped_is_left_alone(
        self, monkeypatch, mock_db_session
    ):
        """A `state` workspace has no `stop`, and neither does a stub."""
        import pydantic_ai_backends as backends_module

        class _Sandbox:
            def __init__(self, api_key=None, sandbox_id=None):
                pass

        monkeypatch.setattr(backends_module, "DaytonaSandbox", _Sandbox, raising=False)
        spec, secrets = _daytona_spec()
        spec.capabilities[0].config["session_scope"] = "run"
        service = SandboxWorkspaceService(mock_db_session)

        workspace = await service.open(spec, identity=_identity(), secrets=secrets)
        await service.close(workspace)


class TestDeletingAConversation:
    async def test_every_workspace_of_the_conversation_goes(self, monkeypatch, mock_db_session):
        rows = [_row(), _row()]
        monkeypatch.setattr(workspace_repo, "list_for_conversation", AsyncMock(return_value=rows))
        deleted = AsyncMock()
        monkeypatch.setattr(workspace_repo, "delete", deleted)

        count = await SandboxWorkspaceService(mock_db_session).purge_for_conversation(
            organization_id=uuid4(), conversation_id=uuid4()
        )

        assert count == 2
        assert deleted.await_count == 2

    async def test_a_container_workspace_is_purged_on_the_service_too(
        self, monkeypatch, mock_db_session
    ):
        """The row would cascade away; the container would sit on the host."""
        from pydantic_ai_backends import remote as remote_module

        from app.core import config as config_module

        monkeypatch.setattr(config_module.settings, "SANDBOXD_URL", "http://sandboxd:8080")
        purged: list[str] = []

        class _Sandbox:
            def __init__(self, url, **kwargs):
                purged.append(kwargs["session_id"])

            def stop(self, purge=False):
                pass

        monkeypatch.setattr(remote_module, "RemoteSandbox", _Sandbox)
        monkeypatch.setattr(
            workspace_repo,
            "list_for_conversation",
            AsyncMock(return_value=[_row(backend="docker", session_id="dc-1")]),
        )
        monkeypatch.setattr(workspace_repo, "delete", AsyncMock())

        await SandboxWorkspaceService(mock_db_session).purge_for_conversation(
            organization_id=uuid4(), conversation_id=uuid4()
        )

        assert purged == ["dc-1"]

    async def test_a_service_that_is_down_does_not_stop_the_deletion(
        self, monkeypatch, mock_db_session
    ):
        """The workspace TTL is the net under exactly this."""
        from pydantic_ai_backends import remote as remote_module

        from app.core import config as config_module

        monkeypatch.setattr(config_module.settings, "SANDBOXD_URL", "http://sandboxd:8080")

        class _Sandbox:
            def __init__(self, url, **kwargs):
                raise RuntimeError("connection refused")

        monkeypatch.setattr(remote_module, "RemoteSandbox", _Sandbox)
        monkeypatch.setattr(
            workspace_repo,
            "list_for_conversation",
            AsyncMock(return_value=[_row(backend="docker", session_id="dc-1")]),
        )
        deleted = AsyncMock()
        monkeypatch.setattr(workspace_repo, "delete", deleted)

        count = await SandboxWorkspaceService(mock_db_session).purge_for_conversation(
            organization_id=uuid4(), conversation_id=uuid4()
        )

        assert count == 1
        deleted.assert_awaited_once()

    async def test_a_state_workspace_needs_no_service_call(self, monkeypatch, mock_db_session):
        monkeypatch.setattr(
            workspace_repo, "list_for_conversation", AsyncMock(return_value=[_row()])
        )
        monkeypatch.setattr(workspace_repo, "delete", AsyncMock())

        assert (
            await SandboxWorkspaceService(mock_db_session).purge_for_conversation(
                organization_id=uuid4(), conversation_id=uuid4()
            )
            == 1
        )

    async def test_a_container_workspace_with_no_service_configured_is_skipped(
        self, monkeypatch, mock_db_session
    ):
        """A deployment that dropped SANDBOXD_URL still deletes its rows."""
        from app.core import config as config_module

        monkeypatch.setattr(config_module.settings, "SANDBOXD_URL", "")
        monkeypatch.setattr(
            workspace_repo,
            "list_for_conversation",
            AsyncMock(return_value=[_row(backend="docker", session_id="dc-1")]),
        )
        monkeypatch.setattr(workspace_repo, "delete", AsyncMock())

        assert (
            await SandboxWorkspaceService(mock_db_session).purge_for_conversation(
                organization_id=uuid4(), conversation_id=uuid4()
            )
            == 1
        )


class TestShowingTheFilesToAPerson:
    """Listing and reading, which the conversation routes proxy.

    No sandbox is started for a container-backed workspace: the files are read
    off the volume the service keeps, which is what makes a conversation from
    last week list its files at all after its session was reaped.
    """

    async def test_a_conversation_with_no_workspace_lists_nothing(
        self, monkeypatch, mock_db_session
    ):
        monkeypatch.setattr(workspace_repo, "list_for_conversation", AsyncMock(return_value=[]))

        found = await SandboxWorkspaceService(mock_db_session).listing(
            organization_id=uuid4(), conversation_id=uuid4()
        )

        assert found is None

    async def test_a_state_workspace_lists_what_it_holds(self, monkeypatch, mock_db_session):
        stored = StateBackend()
        stored.write("/uploads/report.csv", "month,total")
        monkeypatch.setattr(
            workspace_repo,
            "list_for_conversation",
            AsyncMock(return_value=[_row(files=dict(stored.files))]),
        )

        found = await SandboxWorkspaceService(mock_db_session).listing(
            organization_id=uuid4(), conversation_id=uuid4()
        )

        assert found is not None
        _, entries = found
        assert [entry["path"] for entry in entries] == ["/uploads/report.csv"]

    async def test_a_state_file_is_read_back(self, monkeypatch, mock_db_session):
        stored = StateBackend()
        stored.write("/uploads/report.csv", "month,total")
        monkeypatch.setattr(
            workspace_repo,
            "list_for_conversation",
            AsyncMock(return_value=[_row(files=dict(stored.files))]),
        )

        text = await SandboxWorkspaceService(mock_db_session).read_text(
            organization_id=uuid4(), conversation_id=uuid4(), path="/uploads/report.csv"
        )

        assert text is not None
        assert "month,total" in text

    async def test_a_path_that_is_not_there_reads_as_nothing(self, monkeypatch, mock_db_session):
        monkeypatch.setattr(
            workspace_repo, "list_for_conversation", AsyncMock(return_value=[_row(files={})])
        )

        assert (
            await SandboxWorkspaceService(mock_db_session).read_text(
                organization_id=uuid4(), conversation_id=uuid4(), path="/nope.txt"
            )
            is None
        )

    async def test_reading_from_a_conversation_with_no_workspace_is_nothing(
        self, monkeypatch, mock_db_session
    ):
        monkeypatch.setattr(workspace_repo, "list_for_conversation", AsyncMock(return_value=[]))

        assert (
            await SandboxWorkspaceService(mock_db_session).read_text(
                organization_id=uuid4(), conversation_id=uuid4(), path="/a.txt"
            )
            is None
        )

    async def test_a_container_workspace_is_read_off_the_host_volume(
        self, monkeypatch, mock_db_session
    ):
        from pydantic_ai_backends import remote as remote_module

        from app.core import config as config_module

        monkeypatch.setattr(config_module.settings, "SANDBOXD_URL", "http://sandboxd:8080")

        class _Archive:
            def __init__(self, url, token=""):
                pass

            def ls(self, session_id):
                return [{"path": "/workspace/run.py", "size": 12, "is_dir": False}]

            def read(self, session_id, path):
                return "print(1)"

        monkeypatch.setattr(remote_module, "WorkspaceArchive", _Archive, raising=False)
        monkeypatch.setattr(
            workspace_repo,
            "list_for_conversation",
            AsyncMock(return_value=[_row(backend="docker", session_id="dc-1")]),
        )
        service = SandboxWorkspaceService(mock_db_session)

        found = await service.listing(organization_id=uuid4(), conversation_id=uuid4())
        text = await service.read_text(
            organization_id=uuid4(), conversation_id=uuid4(), path="/workspace/run.py"
        )

        assert found is not None
        assert found[1][0]["path"] == "/workspace/run.py"
        assert text == "print(1)"

    async def test_a_service_that_is_misconfigured_raises_rather_than_looking_empty(
        self, monkeypatch, mock_db_session
    ):
        """An empty folder is what a user believes; a 502 is what they can act on."""
        from pydantic_ai_backends import remote as remote_module

        from app.core import config as config_module

        monkeypatch.setattr(config_module.settings, "SANDBOXD_URL", "http://sandboxd:8080")

        class _Archive:
            def __init__(self, url, token=""):
                pass

            def ls(self, session_id):
                raise RuntimeError("no workspace root configured")

        monkeypatch.setattr(remote_module, "WorkspaceArchive", _Archive, raising=False)
        monkeypatch.setattr(
            workspace_repo,
            "list_for_conversation",
            AsyncMock(return_value=[_row(backend="docker", session_id="dc-1")]),
        )

        with pytest.raises(RuntimeError):
            await SandboxWorkspaceService(mock_db_session).listing(
                organization_id=uuid4(), conversation_id=uuid4()
            )

    async def test_a_container_workspace_with_no_service_lists_nothing(
        self, monkeypatch, mock_db_session
    ):
        from app.core import config as config_module

        monkeypatch.setattr(config_module.settings, "SANDBOXD_URL", "")
        monkeypatch.setattr(
            workspace_repo,
            "list_for_conversation",
            AsyncMock(return_value=[_row(backend="docker", session_id="dc-1")]),
        )
        service = SandboxWorkspaceService(mock_db_session)

        found = await service.listing(organization_id=uuid4(), conversation_id=uuid4())

        assert found is not None
        assert found[1] == []
        assert (
            await service.read_text(organization_id=uuid4(), conversation_id=uuid4(), path="/a.txt")
            is None
        )


class TestWhoseWorkspaceItIs:
    """A user seeing a file they never created should be able to find out why."""

    @pytest.mark.parametrize(
        ("scope", "expected"),
        [
            ("conversation", "This conversation"),
            ("user", "Your files for this agent"),
            ("agent", "Shared by everyone who uses this agent"),
            ("run", "This run only"),
        ],
    )
    def test_the_label_names_the_scope_in_words(self, scope: str, expected: str):
        from app.services.sandbox_workspace import owner_label

        assert owner_label(_row(scope=scope)) == expected
