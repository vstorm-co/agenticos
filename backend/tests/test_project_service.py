"""Projects: who may see, work in and change one, its files, and what a run gets.

The refusals are most of it: a private project is a 404 to whoever cannot see it,
a viewer cannot add files or rename it, a chat in a project its author lost stops
reaching the files, and a path outside the project or in the platform's own
directory is refused before anything is written.
"""

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError
from pydantic_ai.workspaces import Workspace, WorkspaceRef
from pydantic_ai_backends.workspaces import StateWorkspaceBackend

from app.agents.capabilities.sandbox._capped import CappedStateBackend
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.project import Project
from app.db.models.resource_grant import Visibility
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.services import project as module
from app.services.project import ProjectService, project_path
from app.services.sandbox_workspace import WorkspaceContents

pytestmark = pytest.mark.anyio

ORG = uuid.uuid4()


def _ctx(role: str = OrgRoleName.OWNER) -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=ORG, role=role)


def _project(**overrides: Any) -> MagicMock:
    project = MagicMock(
        spec=Project,
        id=uuid.uuid4(),
        organization_id=ORG,
        owner_user_id=uuid.uuid4(),
        visibility=Visibility.PRIVATE.value,
        description="Q3 launch",
        instructions="Write in British English.",
        default_agent_id=None,
        backend="service",
        sandbox_connection_id=None,
        workspace_generation=None,
        workspace_move_job_id=None,
        runtime=None,
        created_at=datetime(2026, 10, 17, tzinfo=UTC),
        updated_at=None,
    )
    project.name = "Launch"
    for field, value in overrides.items():
        setattr(project, field, value)
    return project


class _Access:
    """Which permissions the caller holds on the project in hand."""

    def __init__(self, *held: Perm) -> None:
        self.held = set(held)

    async def __call__(
        self, _db: object, _ctx: object, _row: object, perm: Perm, **_: object
    ) -> bool:
        return perm in self.held


def _service(project: MagicMock | None, *held: Perm) -> ProjectService:
    service = ProjectService(MagicMock())
    service.workspaces = MagicMock(
        project_files=AsyncMock(return_value=None),
        project_bytes=AsyncMock(return_value=b"data"),
        purge_project=AsyncMock(),
        open_project=AsyncMock(),
        close=AsyncMock(),
    )
    patcher = [
        patch.object(module.project_repo, "get", AsyncMock(return_value=project)),
        patch.object(module, "resolve_access", _Access(*held)),
    ]
    for started in patcher:
        started.start()
    return service


@pytest.fixture(autouse=True)
def _stop_patches():
    yield
    patch.stopall()


class TestWhoMaySeeAndChangeIt:
    async def test_a_project_the_caller_cannot_see_is_not_found(self) -> None:
        with pytest.raises(NotFoundError):
            await _service(_project()).get(_ctx(), uuid.uuid4())
        with pytest.raises(NotFoundError):
            await _service(None, Perm.PROJECTS_VIEW).get(_ctx(), uuid.uuid4())

    @pytest.mark.parametrize(
        ("perm", "says"),
        [(Perm.PROJECTS_EDIT, "not change it"), (Perm.PROJECTS_USE, "not work in it")],
    )
    async def test_seeing_it_is_not_changing_or_working_in_it(self, perm: Perm, says: str) -> None:
        with pytest.raises(AuthorizationError, match=says):
            await _service(_project(), Perm.PROJECTS_VIEW).get(_ctx(), uuid.uuid4(), perm=perm)

    @pytest.mark.parametrize("perm", [Perm.PROJECTS_VIEW, Perm.PROJECTS_USE, Perm.PROJECTS_EDIT])
    async def test_project_use_and_edit_share_the_transaction_lock(self, perm: Perm) -> None:
        project = _project()
        service = _service(project, Perm.PROJECTS_VIEW, perm)
        assert await service.get(_ctx(), project.id, perm=perm) is project
        assert module.project_repo.get.call_args.kwargs["for_update"] is (
            perm is not Perm.PROJECTS_VIEW
        )

    async def test_a_new_chat_needs_the_right_to_work_in_it(self) -> None:
        project = _project()
        service = _service(project, Perm.PROJECTS_VIEW, Perm.PROJECTS_USE)
        assert await service.check_can_start(_ctx(), project.id) is project

    async def test_its_chats_are_listed_to_whoever_may_see_it(self) -> None:
        project = _project()
        listed = AsyncMock(return_value=([], 0))
        with patch.object(module.ConversationService, "list_project_chats", listed):
            page = await _service(project, Perm.PROJECTS_VIEW).chats(
                _ctx(), project.id, skip=50, limit=50
            )
        assert page == ([], 0)
        assert listed.await_args.args[0] == project.id
        assert (listed.await_args.kwargs["skip"], listed.await_args.kwargs["limit"]) == (50, 50)
        with pytest.raises(NotFoundError):
            await _service(project).chats(_ctx(), project.id, skip=0, limit=50)


class TestCreatingAndChanging:
    async def test_a_project_runs_in_a_container_where_there_is_a_sandbox(self) -> None:
        created = _project()
        service = _service(None)
        host = MagicMock(id=uuid.uuid4())
        connections = MagicMock(ensure_local_connection=AsyncMock(return_value=host))
        with (
            patch.object(module, "SandboxConnectionService", return_value=connections),
            patch.object(module.project_repo, "create", AsyncMock(return_value=created)) as create,
            patch.object(module, "record_audit", AsyncMock()),
        ):
            assert await service.create(_ctx(), ProjectCreate(name="Launch")) is created
        assert create.await_args.kwargs["backend"] == "service"
        assert create.await_args.kwargs["visibility"] == "private"
        # On that host: a new organization default must not open it an empty one.
        assert create.await_args.kwargs["sandbox_connection_id"] == host.id

    async def test_without_a_sandbox_it_keeps_files_and_an_audience_keeps_it_private(self) -> None:
        created = _project()
        service = _service(None)
        sharing = MagicMock(restrict_to=AsyncMock())
        group = uuid.uuid4()
        with (
            patch.object(
                module,
                "SandboxConnectionService",
                return_value=MagicMock(ensure_local_connection=AsyncMock(return_value=None)),
            ),
            patch.object(module.project_repo, "create", AsyncMock(return_value=created)) as create,
            patch.object(module, "SharingService", return_value=sharing),
            patch.object(module, "record_audit", AsyncMock()),
        ):
            await service.create(
                _ctx(),
                ProjectCreate(name="Launch", visibility=Visibility.ORG, group_ids=[group]),
            )
        assert create.await_args.kwargs["backend"] == "state"
        assert create.await_args.kwargs["visibility"] == "private"
        assert sharing.restrict_to.await_args.kwargs["group_ids"] == [group]

    def test_a_team_project_is_refused_rather_than_kept_hidden(self) -> None:
        """No role reaches a project at team scope, so it was its creator's alone."""
        with pytest.raises(ValidationError):
            ProjectCreate(name="Launch", visibility=Visibility.TEAM)
        assert ProjectCreate(name="Launch", visibility="org").visibility is Visibility.ORG

    async def test_a_default_agent_must_be_one_the_caller_can_run(self) -> None:
        service = _service(None)
        with (
            patch.object(module.agent_repo, "get", AsyncMock(return_value=None)),
            pytest.raises(BadRequestError) as refused,
        ):
            await service.create(_ctx(), ProjectCreate(name="x", default_agent_id=uuid.uuid4()))
        assert refused.value.details["fields"][0]["field"] == "default_agent_id"

    async def test_an_update_checks_the_new_default_agent_and_is_recorded(self) -> None:
        project = _project()
        service = _service(project, Perm.PROJECTS_VIEW, Perm.PROJECTS_EDIT, Perm.AGENTS_RUN)
        with (
            patch.object(module.agent_repo, "get", AsyncMock(return_value=MagicMock())),
            patch.object(
                module.organization_assistant_repo, "switched_off", AsyncMock(return_value=set())
            ),
            patch.object(module.project_repo, "update", AsyncMock(return_value=project)) as update,
            patch.object(module, "record_audit", AsyncMock()) as audited,
        ):
            await service.update(
                _ctx(),
                project.id,
                ProjectUpdate(instructions="Short.", default_agent_id=uuid.uuid4()),
            )
        assert update.await_args.kwargs["update_data"]["instructions"] == "Short."
        assert audited.await_args.kwargs["details"] == {
            "fields": ["default_agent_id", "instructions"]
        }

    @pytest.mark.parametrize(
        ("status", "version"),
        [("draft", None), ("archived", uuid.uuid4())],
        ids=["never-published", "archived"],
    )
    async def test_a_default_agent_that_cannot_answer_is_refused(
        self, status: str, version: uuid.UUID | None
    ) -> None:
        """A new chat starts with it, and its first message was refused."""
        project = _project()
        service = _service(project, Perm.PROJECTS_VIEW, Perm.PROJECTS_EDIT, Perm.AGENTS_RUN)
        agent = MagicMock(status=status, current_version_id=version)
        with (
            patch.object(module.agent_repo, "get", AsyncMock(return_value=agent)),
            pytest.raises(BadRequestError) as refused,
        ):
            await service.update(_ctx(), project.id, ProjectUpdate(default_agent_id=uuid.uuid4()))
        assert "published agent" in refused.value.message

    async def test_a_switched_off_assistant_is_refused_as_the_default(self) -> None:
        project = _project()
        service = _service(project, Perm.PROJECTS_VIEW, Perm.PROJECTS_EDIT, Perm.AGENTS_RUN)
        agent = MagicMock(id=uuid.uuid4(), status="published", current_version_id=uuid.uuid4())
        with (
            patch.object(module.agent_repo, "get", AsyncMock(return_value=agent)),
            patch.object(
                module.organization_assistant_repo,
                "switched_off",
                AsyncMock(return_value={agent.id}),
            ),
            pytest.raises(BadRequestError) as refused,
        ):
            await service.update(_ctx(), project.id, ProjectUpdate(default_agent_id=agent.id))
        assert "switched off" in refused.value.message

    async def test_a_runtime_change_is_refused_once_the_container_exists(self) -> None:
        """A run reattaches the container, so the new runtime would be claimed while
        commands still ran in the old one."""
        project = _project(runtime="python")
        service = _service(project, Perm.PROJECTS_VIEW, Perm.PROJECTS_EDIT)
        opened = AsyncMock(return_value=[MagicMock(session_id=None), MagicMock(session_id="s-1")])
        with (
            patch.object(module.agent_workspace_repo, "list_for_project", opened),
            pytest.raises(BadRequestError) as refused,
        ):
            await service.update(_ctx(), project.id, ProjectUpdate(runtime="workbench"))
        assert refused.value.details["fields"][0]["field"] == "runtime"

    async def test_a_runtime_change_before_any_container_is_taken(self) -> None:
        project = _project(runtime="python")
        service = _service(project, Perm.PROJECTS_VIEW, Perm.PROJECTS_EDIT)
        with (
            patch.object(
                module.agent_workspace_repo, "list_for_project", AsyncMock(return_value=[])
            ),
            patch.object(module.project_repo, "update", AsyncMock(return_value=project)) as update,
            patch.object(module, "record_audit", AsyncMock()),
        ):
            await service.update(_ctx(), project.id, ProjectUpdate(runtime="workbench"))
        assert update.await_args.kwargs["update_data"] == {"runtime": "workbench"}

    async def test_renaming_without_a_new_default_agent_checks_no_agent(self) -> None:
        project = _project()
        service = _service(project, Perm.PROJECTS_VIEW, Perm.PROJECTS_EDIT)
        with (
            patch.object(module.agent_repo, "get", AsyncMock()) as agent_lookup,
            patch.object(module.project_repo, "update", AsyncMock(return_value=project)),
            patch.object(module, "record_audit", AsyncMock()),
        ):
            assert (
                await service.update(_ctx(), project.id, ProjectUpdate(name="Launch v2")) is project
            )
        agent_lookup.assert_not_awaited()

    async def test_deleting_purges_the_container_keeps_the_chats_and_drops_the_grants(self) -> None:
        project = _project()
        service = _service(project, Perm.PROJECTS_VIEW, Perm.PROJECTS_EDIT)
        orphan = uuid.uuid4()
        with (
            patch.object(
                module.project_repo, "ownerless_chat_ids", AsyncMock(return_value=[orphan])
            ),
            patch.object(module.ConversationService, "forget_stored_files", AsyncMock()) as forgot,
            patch.object(module.project_repo, "detach_conversations", AsyncMock()) as detached,
            patch.object(module.resource_grant_repo, "delete_for_resource", AsyncMock()) as grants,
            patch.object(module.project_repo, "delete", AsyncMock()) as deleted,
            patch.object(module, "record_audit", AsyncMock()),
        ):
            await service.delete(_ctx(), project.id)
        service.workspaces.purge_project.assert_awaited_once()
        # The chats deleted with it take their files: nothing else would unlink them.
        assert forgot.await_args.args[1] == [orphan]
        detached.assert_awaited_once()
        assert grants.await_args.kwargs["resource_type"] == "project"
        deleted.assert_awaited_once()


class TestListing:
    async def test_each_project_says_what_the_caller_may_do_and_how_many_chats_it_holds(
        self,
    ) -> None:
        agent = MagicMock(id=uuid.uuid4(), status="published", current_version_id=uuid.uuid4())
        agent.name = "Researcher"
        hidden = MagicMock(id=uuid.uuid4())
        hidden.name = "Private agent"
        # Runnable when it was set, archived since: a new chat would be refused.
        archived = MagicMock(id=uuid.uuid4(), status="archived", current_version_id=uuid.uuid4())
        archived.name = "Old agent"
        mine = _project(default_agent_id=agent.id)
        # A default agent the reader may not see: neither named nor identified.
        theirs = _project(default_agent_id=hidden.id)
        stale = _project(default_agent_id=archived.id)
        service = _service(None)
        with (
            patch.object(module, "visible_resource_ids", AsyncMock(return_value=None)),
            patch.object(module, "shared_with_group", AsyncMock(return_value=None)),
            patch.object(
                module.project_repo,
                "list_visible",
                AsyncMock(return_value=([mine, theirs, stale], 3)),
            ) as listed,
            patch.object(
                module.project_repo,
                "chat_activity",
                AsyncMock(return_value={mine.id: (3, datetime(2026, 10, 17, tzinfo=UTC))}),
            ),
            patch.object(
                module,
                "groups_sharing",
                AsyncMock(return_value={mine.id: ["Finance"], theirs.id: [], stale.id: []}),
            ),
            patch.object(
                module,
                "accessible_ids",
                AsyncMock(side_effect=[{mine.id}, {mine.id}, {agent.id, archived.id}]),
            ) as accessible,
            patch.object(
                module.agent_repo,
                "get_many",
                AsyncMock(return_value={agent.id: agent, hidden.id: hidden, archived.id: archived}),
            ),
            patch.object(
                module.organization_assistant_repo, "switched_off", AsyncMock(return_value=set())
            ),
        ):
            page = await service.list_projects(_ctx(), search="lau")

        assert listed.await_args.kwargs["see_all"] is True
        first, second, third = page.items
        assert (third.default_agent_id, third.default_agent_name) == (None, None)
        assert (first.chat_count, first.can_use, first.can_edit) == (3, True, True)
        assert (first.default_agent_id, first.default_agent_name) == (agent.id, "Researcher")
        assert (second.default_agent_id, second.default_agent_name) == (None, None)
        # Runnable, not merely visible: a new chat starts with it.
        assert accessible.await_args_list[2].args[3] is Perm.AGENTS_RUN
        assert first.shared_groups == ["Finance"]
        assert (second.chat_count, second.can_use, second.default_agent_name) == (0, False, None)

    async def test_one_project_reads_the_same_way(self) -> None:
        project = _project(sandbox_connection_id=uuid.uuid4())
        service = _service(None)
        with (
            patch.object(
                module.sandbox_connection_repo,
                "names_for_ids",
                AsyncMock(return_value={project.sandbox_connection_id: "Local sandbox"}),
            ),
            patch.object(module.project_repo, "chat_activity", AsyncMock(return_value={})),
            patch.object(module, "groups_sharing", AsyncMock(return_value={project.id: []})),
            patch.object(module, "accessible_ids", AsyncMock(side_effect=[set(), set(), set()])),
            patch.object(module.agent_repo, "get_many", AsyncMock(return_value={})),
        ):
            read = await service.read(_ctx(), project)
        assert (read.name, read.chat_count, read.can_edit) == ("Launch", 0, False)

        assert read.sandbox_connection_name == "Local sandbox"


class TestARunInAProject:
    async def test_a_chat_outside_a_project_runs_as_before(self) -> None:
        service = _service(None)
        assert await service.for_run(_ctx(), None) is None
        with patch.object(
            module.conversation_repo,
            "get_conversation_by_id",
            AsyncMock(return_value=MagicMock(organization_id=ORG, project_id=None)),
        ):
            assert await service.for_run(_ctx(), uuid.uuid4()) is None
        with patch.object(
            module.conversation_repo,
            "get_conversation_by_id",
            AsyncMock(
                return_value=MagicMock(organization_id=uuid.uuid4(), project_id=uuid.uuid4())
            ),
        ):
            assert await service.for_run(_ctx(), uuid.uuid4()) is None

    async def test_a_chat_in_a_project_works_in_it_while_its_author_may(self) -> None:
        project = _project()
        chat = MagicMock(organization_id=ORG, project_id=project.id)
        with patch.object(
            module.conversation_repo, "get_conversation_by_id", AsyncMock(return_value=chat)
        ):
            assert (
                await _service(project, Perm.PROJECTS_USE).for_run(_ctx(), uuid.uuid4()) is project
            )
            with pytest.raises(AuthorizationError, match="no longer work in"):
                await _service(project, Perm.PROJECTS_VIEW).for_run(_ctx(), uuid.uuid4())
            assert await _service(None).for_run(_ctx(), uuid.uuid4()) is None


class TestFiles:
    @pytest.mark.parametrize(
        ("given", "kept"),
        [
            ("reports/q3.pdf", "reports/q3.pdf"),
            # As a stored project lists it: the leading slash is the project's root.
            ("/notes/a.md/", "notes/a.md"),
            ("a/./b", "a/b"),
        ],
    )
    def test_a_path_inside_the_project_is_kept_tidy(self, given: str, kept: str) -> None:
        assert project_path(given) == kept

    @pytest.mark.parametrize(
        "path",
        [
            "",
            ".",
            "/",
            "../etc/passwd",
            "/../etc",
            "a/../../b",
            "/.agenticos/x",
            "skills/s/SKILL.md",
        ],
    )
    def test_a_path_outside_it_or_in_the_platforms_own_folders_is_refused(self, path: str) -> None:
        with pytest.raises(BadRequestError):
            project_path(path)

    async def test_listing_an_empty_project_starts_nothing(self) -> None:
        project = _project()
        service = _service(project, Perm.PROJECTS_VIEW)
        _same, row, contents = await service.files(_ctx(), project.id)
        assert row is None and contents.entries == []

        listed = (MagicMock(), WorkspaceContents(entries=[{"path": "a.md"}]))
        service.workspaces.project_files = AsyncMock(return_value=listed)
        _same, row, contents = await service.files(_ctx(), project.id)
        assert row is listed[0] and contents.entries == [{"path": "a.md"}]
        assert await service.file_bytes(_ctx(), project.id, path="a.md") == b"data"

    @pytest.mark.security
    @pytest.mark.parametrize(
        "path",
        [
            ".agenticos/coding-agent/claude_code-thread.session",
            "/.agenticos/coding-agent/codex-thread.session",
            "notes/../.agenticos/coding-agent/x.exit",
        ],
    )
    async def test_a_platform_file_cannot_be_fetched_by_naming_it(self, path: str) -> None:
        """The browser never lists them, and an empty listing is no proof a file
        is absent - so naming one must not reach the host."""
        project = _project()
        service = _service(project, Perm.PROJECTS_VIEW)
        service.workspaces.project_bytes = AsyncMock(return_value=b"session")
        with pytest.raises(NotFoundError):
            await service.file_bytes(_ctx(), project.id, path=path)
        service.workspaces.project_bytes.assert_not_awaited()

    async def test_adding_a_file_writes_it_into_its_folder_and_closes_the_container(self) -> None:
        project = _project()
        service = _service(project, Perm.PROJECTS_VIEW, Perm.PROJECTS_USE)
        workspace = MagicMock(make_dir=AsyncMock(), write_bytes=AsyncMock())
        service.workspaces.open_project = AsyncMock(return_value=MagicMock(workspace=workspace))
        with patch.object(module, "record_audit", AsyncMock()) as audited:
            path = await service.add_file(_ctx(), project.id, path="data/in.csv", data=b"a,b")
            await service.add_file(_ctx(), project.id, path="top.txt", data=b"x")
        assert path == "data/in.csv"
        workspace.make_dir.assert_awaited_once_with("data")
        assert workspace.write_bytes.await_count == 2
        assert service.workspaces.close.await_count == 2
        assert audited.await_args.kwargs["details"] == {"path": "top.txt"}

    async def test_a_file_over_the_limit_is_refused_before_anything_opens(self) -> None:
        project = _project()
        service = _service(project, Perm.PROJECTS_VIEW, Perm.PROJECTS_USE)
        with (
            patch.object(module.settings, "MAX_UPLOAD_SIZE_MB", 0),
            pytest.raises(BadRequestError, match="up to 0 MB"),
        ):
            await service.add_file(_ctx(), project.id, path="a.bin", data=b"x")
        service.workspaces.open_project.assert_not_awaited()

    async def test_a_viewer_cannot_add_files(self) -> None:
        project = _project()
        with pytest.raises(AuthorizationError):
            await _service(project, Perm.PROJECTS_VIEW).add_folder(_ctx(), project.id, path="docs")

    async def test_a_folder_is_made_and_a_path_removed_by_the_backend_that_holds_it(self) -> None:
        project = _project()
        service = _service(project, Perm.PROJECTS_VIEW, Perm.PROJECTS_USE)
        container = MagicMock(
            make_dir=AsyncMock(),
            run=AsyncMock(return_value=MagicMock(exit_code=0, stderr="")),
            remove=AsyncMock(),
        )
        service.workspaces.open_project = AsyncMock(
            side_effect=[
                MagicMock(workspace=container, kind="service"),
                MagicMock(workspace=container, kind="service"),
                MagicMock(workspace=container, kind="state"),
            ]
        )
        with patch.object(module, "record_audit", AsyncMock()):
            assert await service.add_folder(_ctx(), project.id, path="docs/") == "docs"
            await service.remove(_ctx(), project.id, path="docs")
            await service.remove(_ctx(), project.id, path="notes.md")
        container.make_dir.assert_awaited_once_with("docs")
        assert container.run.await_args.args[0] == ["rm", "-rf", "--", "docs"]
        container.remove.assert_awaited_once_with("notes.md")
        assert service.workspaces.close.await_count == 3

    async def test_a_stored_projects_file_is_removed_by_the_path_its_listing_gave(self) -> None:
        """A stored project lists `/reports/q3.pdf`, and removing it by that path was
        refused as outside the project - every file, on a deployment without sandboxd."""
        document = CappedStateBackend({}, (), max_bytes=10_000_000)
        workspace = Workspace(
            StateWorkspaceBackend({"k": document}, ref=WorkspaceRef(provider="state", id="k"))
        )
        await workspace.write_bytes("reports/q3.pdf", b"x")
        (listed,) = document.files
        project = _project()
        service = _service(project, Perm.PROJECTS_VIEW, Perm.PROJECTS_USE)
        service.workspaces.open_project = AsyncMock(
            return_value=MagicMock(workspace=workspace, kind="state")
        )
        with patch.object(module, "record_audit", AsyncMock()):
            await service.remove(_ctx(), project.id, path=listed)

        assert listed.startswith("/") and document.files == {}

    async def test_a_removal_the_container_refused_is_not_reported_as_done(self) -> None:
        """A folder an agent made read-only stays; the answer and the audit must say so."""
        project = _project()
        service = _service(project, Perm.PROJECTS_VIEW, Perm.PROJECTS_USE)
        refused = MagicMock(exit_code=1, stderr="rm: cannot remove 'docs': Permission denied")
        container = MagicMock(run=AsyncMock(return_value=refused))
        service.workspaces.open_project = AsyncMock(
            return_value=MagicMock(workspace=container, kind="service")
        )
        with (
            patch.object(module, "record_audit", AsyncMock()) as audited,
            pytest.raises(BadRequestError, match="would not remove") as refusal,
        ):
            await service.remove(_ctx(), project.id, path="docs")
        audited.assert_not_awaited()
        # The host's own words go to the log, not to the reader.
        assert "Permission denied" not in str(refusal.value.details)
        service.workspaces.close.assert_awaited_once()


class TestFileManagement:
    def setup_method(self) -> None:
        self.project = _project()
        self.service = _service(self.project, Perm.PROJECTS_VIEW, Perm.PROJECTS_USE)
        self.document = CappedStateBackend({}, (), max_bytes=10_000_000)
        self.workspace = Workspace(
            StateWorkspaceBackend({"k": self.document}, ref=WorkspaceRef(provider="state", id="k"))
        )
        self.opened = MagicMock(workspace=self.workspace, document=self.document, kind="state")
        self.service.workspaces.open_project = AsyncMock(return_value=self.opened)
        patch.object(module.agent_workspace_repo, "lock_project_files", AsyncMock()).start()
        patch.object(module, "record_audit", AsyncMock()).start()

    async def test_rename_keeps_binary_contents_and_empty_subfolders(self) -> None:
        await self.workspace.write_bytes("docs/data.bin", b"\x00\xff")
        await self.workspace.make_dir("docs/empty")
        before = self.document.files["/docs/data.bin"]
        assert (
            await self.service.move_path(
                _ctx(), self.project.id, source="/docs", destination="notes"
            )
            == "notes"
        )
        assert await self.workspace.read_bytes("notes/data.bin") == b"\x00\xff"
        assert await self.workspace.exists("notes/empty")
        assert not await self.workspace.exists("docs")
        assert self.document.files["/notes/data.bin"] == before
        self.service.workspaces.close.assert_awaited_once()

    @pytest.mark.parametrize("destination", ["docs", "docs/nested", "../out", ".agenticos/x"])
    async def test_a_move_cannot_escape_or_move_into_itself(self, destination: str) -> None:
        await self.workspace.make_dir("docs")
        with pytest.raises(BadRequestError):
            await self.service.move_path(
                _ctx(), self.project.id, source="docs", destination=destination
            )
        assert await self.workspace.exists("docs")

    async def test_move_refuses_collisions_missing_sources_and_missing_parents(self) -> None:
        from app.core.exceptions import AlreadyExistsError

        await self.workspace.write_bytes("a.txt", b"a")
        await self.workspace.write_bytes("b.txt", b"b")
        for origin, target, error in [
            ("a.txt", "b.txt", AlreadyExistsError),
            ("absent", "c.txt", NotFoundError),
            ("a.txt", "absent/a.txt", BadRequestError),
            ("a.txt", "b.txt/a.txt", BadRequestError),
        ]:
            with pytest.raises(error):
                await self.service.move_path(
                    _ctx(), self.project.id, source=origin, destination=target
                )
        assert await self.workspace.read_bytes("a.txt") == b"a"
        assert await self.workspace.read_bytes("b.txt") == b"b"

    async def test_edits_preserve_whitespace_and_refuse_a_changed_revision(self) -> None:
        from app.core.exceptions import AlreadyExistsError

        await self.workspace.write_bytes("a.txt", b"old")
        self.service.workspaces.project_bytes = AsyncMock(return_value=b"old")
        original = await self.service.editable_file(_ctx(), self.project.id, path="a.txt")
        saved = await self.service.edit_file(
            _ctx(), self.project.id, path="a.txt", content="  new\n", revision=original.revision
        )
        assert await self.workspace.read_bytes("a.txt") == b"  new\n"
        assert saved.revision != original.revision
        with pytest.raises(AlreadyExistsError):
            await self.service.edit_file(
                _ctx(), self.project.id, path="a.txt", content="stale", revision=original.revision
            )
        assert await self.workspace.read_bytes("a.txt") == b"  new\n"
        with pytest.raises(NotFoundError):
            await self.service.edit_file(
                _ctx(), self.project.id, path="missing", content="new", revision=original.revision
            )

    @pytest.mark.parametrize(
        "data",
        [b"\x00binary", b"\xff", b"x" * 1_048_577],
        ids=["binary", "invalid-utf8", "over-one-mib"],
    )
    async def test_the_editor_refuses_binary_and_overlarge_files(self, data: bytes) -> None:
        self.service.workspaces.project_bytes = AsyncMock(return_value=data)
        with pytest.raises(BadRequestError):
            await self.service.editable_file(_ctx(), self.project.id, path="a.txt")

    async def test_a_viewer_cannot_move_or_edit_files(self) -> None:
        service = _service(self.project, Perm.PROJECTS_VIEW)
        with pytest.raises(AuthorizationError):
            await service.move_path(_ctx(), self.project.id, source="a", destination="b")
        with pytest.raises(AuthorizationError):
            await service.editable_file(_ctx(), self.project.id, path="a")
        with pytest.raises(AuthorizationError):
            await service.edit_file(
                _ctx(), self.project.id, path="a", content="b", revision="0" * 64
            )
        service.workspaces.open_project.assert_not_awaited()


@pytest.mark.parametrize("code,still_exists", [(0, False), (1, False), (0, True)])
async def test_a_remote_move_uses_no_clobber_and_reports_a_refused_move(
    code: int, still_exists: bool
) -> None:
    project = _project()
    service = _service(project, Perm.PROJECTS_VIEW, Perm.PROJECTS_USE)
    remote = MagicMock(
        exists=AsyncMock(side_effect=[True, False, True, still_exists]),
        stat=AsyncMock(return_value=MagicMock(is_dir=True)),
        run=AsyncMock(return_value=MagicMock(exit_code=code)),
    )
    service.workspaces.open_project = AsyncMock(
        return_value=MagicMock(workspace=remote, document=None)
    )
    with (
        patch.object(module.agent_workspace_repo, "lock_project_files", AsyncMock()),
        patch.object(module, "record_audit", AsyncMock()) as audit,
    ):
        if code != 0 or still_exists:
            with pytest.raises(BadRequestError, match="Could not move"):
                await service.move_path(_ctx(), project.id, source="a.txt", destination="b.txt")
            audit.assert_not_awaited()
        else:
            assert (
                await service.move_path(_ctx(), project.id, source="a.txt", destination="b.txt")
                == "b.txt"
            )
    assert remote.run.await_args.args[0] == ["mv", "-T", "-n", "--", "a.txt", "b.txt"]
    service.workspaces.close.assert_awaited_once()


@pytest.mark.parametrize(
    "operation", ["add_file", "add_folder", "remove", "move_path", "edit_file"]
)
async def test_a_failed_flush_is_not_reported_as_a_successful_file_mutation(operation: str) -> None:
    import hashlib

    from app.core.exceptions import WorkspaceCapacityError
    from app.services.sandbox_workspace import WorkspaceFlushFailure

    project = _project()
    service = _service(project, Perm.PROJECTS_VIEW, Perm.PROJECTS_USE)
    document = CappedStateBackend({}, (), max_bytes=10_000_000)
    workspace = Workspace(
        StateWorkspaceBackend({"k": document}, ref=WorkspaceRef(provider="state", id="k"))
    )
    await workspace.write_bytes("a.txt", b"old")
    service.workspaces.open_project = AsyncMock(
        return_value=MagicMock(workspace=workspace, document=document, kind="state")
    )
    service.workspaces.close = AsyncMock(
        return_value=WorkspaceFlushFailure(WorkspaceCapacityError(message="Too large", details={}))
    )
    with (
        patch.object(module.agent_workspace_repo, "lock_project_files", AsyncMock()),
        patch.object(module, "record_audit", AsyncMock()) as audit,
        pytest.raises(WorkspaceCapacityError),
    ):
        if operation == "add_file":
            await service.add_file(_ctx(), project.id, path="b.txt", data=b"new")
        elif operation == "add_folder":
            await service.add_folder(_ctx(), project.id, path="docs")
        elif operation == "remove":
            await service.remove(_ctx(), project.id, path="a.txt")
        elif operation == "move_path":
            await service.move_path(_ctx(), project.id, source="a.txt", destination="b.txt")
        else:
            await service.edit_file(
                _ctx(),
                project.id,
                path="a.txt",
                content="new",
                revision=hashlib.sha256(b"old").hexdigest(),
            )
    audit.assert_not_awaited()


def test_file_paths_cannot_contain_control_characters() -> None:
    with pytest.raises(BadRequestError, match="control characters"):
        project_path("a\x00b")


async def test_a_project_can_choose_stored_files_even_when_a_sandbox_is_available() -> None:
    created = _project(backend="state")
    service = _service(None)
    connections = MagicMock(ensure_local_connection=AsyncMock())
    with (
        patch.object(module, "SandboxConnectionService", return_value=connections),
        patch.object(module.project_repo, "create", AsyncMock(return_value=created)) as create,
        patch.object(module, "record_audit", AsyncMock()),
    ):
        await service.create(_ctx(), ProjectCreate(name="Notes", backend="state"))
    assert create.await_args.kwargs["backend"] == "state"
    assert create.await_args.kwargs["sandbox_connection_id"] is None
    connections.ensure_local_connection.assert_not_awaited()


async def test_a_project_pins_the_sandbox_connection_chosen_at_creation() -> None:
    created = _project()
    service = _service(None)
    host = MagicMock(id=uuid.uuid4(), is_active=True)
    connections = MagicMock(get=AsyncMock(return_value=host), ensure_local_connection=AsyncMock())
    with (
        patch.object(module, "SandboxConnectionService", return_value=connections),
        patch.object(module.project_repo, "create", AsyncMock(return_value=created)) as create,
        patch.object(module, "record_audit", AsyncMock()),
    ):
        await service.create(
            _ctx(), ProjectCreate(name="Build", backend="service", sandbox_connection_id=host.id)
        )
    assert create.await_args.kwargs["backend"] == "service"
    assert create.await_args.kwargs["sandbox_connection_id"] == host.id
    connections.ensure_local_connection.assert_not_awaited()


async def test_project_sandbox_selection_refuses_inactive_unavailable_and_unauthorized_hosts() -> (
    None
):
    service = _service(None)
    host = MagicMock(id=uuid.uuid4(), is_active=False)
    connections = MagicMock(
        get=AsyncMock(return_value=host), ensure_local_connection=AsyncMock(return_value=None)
    )
    with patch.object(module, "SandboxConnectionService", return_value=connections):
        with pytest.raises(BadRequestError):
            await service.create(
                _ctx(),
                ProjectCreate(name="Build", backend="service", sandbox_connection_id=host.id),
            )
        with pytest.raises(BadRequestError):
            await service.create(
                _ctx(), ProjectCreate(name="Build", backend="state", sandbox_connection_id=host.id)
            )
        with pytest.raises(BadRequestError):
            await service.create(_ctx(), ProjectCreate(name="Build", backend="service"))
        with (
            patch.object(module.AuthContext, "has", return_value=False),
            pytest.raises(AuthorizationError),
        ):
            await service.create(_ctx(), ProjectCreate(name="Build", sandbox_connection_id=host.id))
