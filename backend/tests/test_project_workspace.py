"""A project's container: one per project, every agent's in it, no one agent's.

What `tests/test_project_service.py` cannot show is below the service: the key a
project's container is opened under is the same whichever agent or run asks, a
run outside a project cannot reach one, the row it creates carries the project
and no agent, and a run in a project is given the container - and the project's
instructions - even when its agent keeps no workspace of its own.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.capabilities.sandbox._identity import (
    WorkspaceIdentity,
    WorkspaceScopeUnavailable,
    scope_key,
)
from app.agents.spec import AgentSpec
from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_workspace import AgentWorkspace
from app.repositories import agent_workspace as workspace_repo
from app.services.agent_runner import _in_project
from app.services.sandbox_workspace import (
    SandboxWorkspaceService,
    WorkspaceContents,
    access_label,
    owner_label,
)

pytestmark = pytest.mark.anyio


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)


def _project(**overrides: object) -> SimpleNamespace:
    fields: dict[str, object] = {
        "id": uuid4(),
        "name": "Launch",
        "description": None,
        "instructions": "",
        "backend": "state",
        "sandbox_connection_id": None,
        "runtime": None,
        "workspace_generation": None,
        "workspace_move_job_id": None,
    }
    return SimpleNamespace(**{**fields, **overrides})


def _row(**overrides: object) -> AgentWorkspace:
    row = AgentWorkspace(
        id=uuid4(),
        organization_id=uuid4(),
        agent_id=None,
        project_id=uuid4(),
        scope="project",
        scope_key="dp-cafe",
        backend="state",
        files=None,
        bytes_total=0,
        version=0,
    )
    for name, value in overrides.items():
        setattr(row, name, value)
    return row


class TestOneContainerPerProject:
    def test_every_agent_and_run_in_a_project_opens_the_same_one(self) -> None:
        organization, project = uuid4(), uuid4()

        def key() -> str:
            identity = WorkspaceIdentity(
                organization_id=organization, agent_id=uuid4(), run_id=uuid4(), project_id=project
            )
            return scope_key(identity, "project", "state")

        assert key() == key()

    def test_a_run_outside_a_project_cannot_reach_one(self) -> None:
        identity = WorkspaceIdentity(organization_id=uuid4(), agent_id=uuid4(), run_id=uuid4())
        with pytest.raises(WorkspaceScopeUnavailable, match="not in a project"):
            scope_key(identity, "project", "state")

    def test_only_a_project_can_be_opened_without_an_agents_run(self) -> None:
        identity = WorkspaceIdentity(
            organization_id=uuid4(), agent_id=None, run_id=None, project_id=uuid4()
        )
        with pytest.raises(WorkspaceScopeUnavailable, match="without an agent's run"):
            scope_key(identity, "conversation", "state")

    def test_its_labels_say_who_shares_it(self) -> None:
        assert owner_label(_row()) == "This project, shared by every chat in it"
        assert access_label(_row()) == "Everybody the project is shared with"


class TestOpeningItOutsideARun:
    async def test_the_row_it_creates_is_the_projects_and_no_agents(
        self, monkeypatch: pytest.MonkeyPatch, mock_db_session: MagicMock
    ) -> None:
        project = _project()
        created = AsyncMock(return_value=_row(project_id=project.id))
        monkeypatch.setattr(workspace_repo, "get_by_key", AsyncMock(return_value=None))
        monkeypatch.setattr(workspace_repo, "create", created)

        opened = await SandboxWorkspaceService(mock_db_session).open_project(_ctx(), project)

        assert opened.kind == "state"
        assert created.await_args.kwargs["agent_id"] is None
        assert created.await_args.kwargs["project_id"] == project.id
        assert created.await_args.kwargs["scope"] == "project"

    async def test_an_empty_project_has_nothing_to_list_read_or_purge(
        self, monkeypatch: pytest.MonkeyPatch, mock_db_session: MagicMock
    ) -> None:
        monkeypatch.setattr(workspace_repo, "get_for_project", AsyncMock(return_value=None))
        monkeypatch.setattr(workspace_repo, "list_for_project", AsyncMock(return_value=[]))
        purged = AsyncMock()
        monkeypatch.setattr(SandboxWorkspaceService, "_purge_remote", purged)
        service = SandboxWorkspaceService(mock_db_session)

        assert await service.project_files(_ctx(), _project()) is None
        with pytest.raises(NotFoundError, match="holds no files"):
            await service.project_bytes(_ctx(), _project(), path="a.md")
        await service.purge_project(_ctx(), _project())
        purged.assert_not_awaited()

    async def test_a_held_project_is_listed_read_and_its_container_purged(
        self, monkeypatch: pytest.MonkeyPatch, mock_db_session: MagicMock
    ) -> None:
        row = _row(backend="service")
        contents = WorkspaceContents(entries=[])
        moved_from = _row(backend="service")
        monkeypatch.setattr(workspace_repo, "get_for_project", AsyncMock(return_value=row))
        # A project moved to another connection left a container on the first.
        monkeypatch.setattr(
            workspace_repo, "list_for_project", AsyncMock(return_value=[row, moved_from])
        )
        monkeypatch.setattr(SandboxWorkspaceService, "_tiled", AsyncMock(return_value=contents))
        monkeypatch.setattr(SandboxWorkspaceService, "_browsable", AsyncMock(return_value=contents))
        monkeypatch.setattr(SandboxWorkspaceService, "_bytes_from", AsyncMock(return_value=b"hi"))
        purged = AsyncMock()
        monkeypatch.setattr(SandboxWorkspaceService, "_purge_remote", purged)
        service = SandboxWorkspaceService(mock_db_session)

        assert await service.project_files(_ctx(), _project()) == (row, contents)
        assert await service.project_bytes(_ctx(), _project(), path="a.md") == b"hi"
        await service.purge_project(_ctx(), _project())
        assert [call.args[1] for call in purged.await_args_list] == [row, moved_from]

    async def test_a_stored_project_has_no_host_to_purge(
        self, monkeypatch: pytest.MonkeyPatch, mock_db_session: MagicMock
    ) -> None:
        monkeypatch.setattr(workspace_repo, "list_for_project", AsyncMock(return_value=[_row()]))
        purged = AsyncMock()
        monkeypatch.setattr(SandboxWorkspaceService, "_purge_remote", purged)

        await SandboxWorkspaceService(mock_db_session).purge_project(_ctx(), _project())

        purged.assert_not_awaited()


class TestARunInAProject:
    def test_an_agent_without_sandbox_gets_project_files_but_not_shell_tools(self) -> None:
        project = _project(description="The Q3 launch.", instructions="  Cite sources.  ")
        spec = _in_project(AgentSpec(name="Writer", instructions="You write."), project)
        assert [binding.id for binding in spec.capabilities] == ["projects"]
        assert spec.instructions.startswith("You write.\n\n## Project context")
        assert "The Q3 launch." in spec.instructions
        assert "Cite sources." in spec.instructions
        assert "<project_reference>" in spec.instructions
        assert "within your own and the platform's rules" in spec.instructions

    def test_a_files_only_project_does_not_remove_the_agents_own_coding_toolchain(self) -> None:
        coder = AgentSpec(
            name="Coder",
            capabilities=[
                {"id": "coding_agent", "config": {"harness": "claude_code"}},
                {"id": "web_search"},
                {"id": "sandbox", "config": {"backend": "service"}},
            ],
        )
        stored = _in_project(coder, _project())
        assert [binding.id for binding in stored.capabilities] == [
            "coding_agent",
            "web_search",
            "sandbox",
            "projects",
        ]
        assert stored.capabilities[2].config["backend"] == "state"
        assert coder.capabilities[2].config["backend"] == "service"
        assert "Files-only projects have no executor" in stored.instructions

    @pytest.mark.security
    def test_explicitly_disabled_shell_capability_is_not_enabled_by_project_context(self) -> None:
        spec = AgentSpec(
            name="Writer",
            capabilities=[
                {
                    "id": "sandbox",
                    "enabled": False,
                    "approval": "required",
                    "config": {"include_execute": False},
                }
            ],
        )
        ran = _in_project(spec, _project(backend="service"))
        assert [binding.id for binding in ran.capabilities] == ["sandbox", "projects"]
        assert ran.capabilities[0] == spec.capabilities[0]
        assert not ran.capabilities[0].enabled

    @pytest.mark.security
    def test_project_files_keep_the_authors_shell_visibility_and_approvals(self) -> None:
        connection = uuid4()
        project = _project(backend="service", sandbox_connection_id=connection, runtime="python")
        spec = AgentSpec(
            name="Coder",
            capabilities=[
                {
                    "id": "sandbox",
                    "config": {
                        "backend": "service",
                        "session_scope": "agent",
                        "include_execute": False,
                    },
                    "approval": "required",
                }
            ],
        )
        ran = _in_project(spec, project)
        sandbox = ran.capabilities[0]
        assert sandbox.approval == "required"
        assert sandbox.enabled
        assert not sandbox.config["include_execute"]
        assert sandbox.config["connection_id"] == str(connection)
        assert sandbox.config["runtime"] == "python"
        assert spec.capabilities[0].config["session_scope"] == "agent"


@pytest.mark.security
@pytest.mark.parametrize("moving", [False, True])
async def test_opening_a_project_workspace_rechecks_its_current_generation(monkeypatch, moving):
    from app.services import project_workspace_guard

    ctx = _ctx()
    old = _project()
    current = _project(
        id=old.id, backend="service", sandbox_connection_id=uuid4(), workspace_generation=uuid4()
    )
    guard = AsyncMock(return_value=current)
    if moving:
        guard.side_effect = AlreadyExistsError(message="Transfer in progress")
    monkeypatch.setattr(project_workspace_guard, "project_for_workspace", guard)
    service = SandboxWorkspaceService(MagicMock())
    opened = MagicMock()
    service._open_config = AsyncMock(return_value=opened)
    identity = WorkspaceIdentity(
        organization_id=ctx.organization_id, agent_id=uuid4(), run_id=uuid4(), project_id=old.id
    )
    spec = _in_project(AgentSpec(name="Writer", capabilities=[{"id": "sandbox"}]), old)
    if moving:
        with pytest.raises(AlreadyExistsError):
            await service.open(spec, ctx=ctx, identity=identity, scope_override="project")
        service._open_config.assert_not_awaited()
    else:
        result = await service.open(spec, ctx=ctx, identity=identity, scope_override="project")
        assert result is opened
        config = service._open_config.call_args.args[0]
        assert config.backend == "service"
        assert config.connection_id == current.sandbox_connection_id
        assert (
            service._open_config.call_args.kwargs["identity"].project_workspace_id
            == current.workspace_generation
        )
        assert identity.project_workspace_id is None
    guard.assert_awaited_once_with(service.db, ctx, old.id)
