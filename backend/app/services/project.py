"""Projects - a shared container, standing instructions and the chats held in them.

This module owns a project as a row, who may do what with it, and its files as a
person manages them. What a run does differently inside one - the project's
container in place of the agent's own, its instructions after the agent's - is
the runner's, through :meth:`ProjectService.for_run`.
"""

from __future__ import annotations

import logging
import posixpath
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.config import settings
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent, AgentStatus
from app.db.models.agent_workspace import AgentWorkspace
from app.db.models.conversation import Conversation
from app.db.models.project import Project
from app.db.updates import writable
from app.repositories import (
    agent_repo,
    agent_workspace_repo,
    conversation_repo,
    organization_assistant_repo,
    project_repo,
    resource_grant_repo,
)
from app.schemas.project import ProjectCreate, ProjectList, ProjectRead, ProjectUpdate
from app.services.access import (
    AGENT,
    PROJECT,
    accessible_ids,
    resolve_access,
    visible_resource_ids,
)
from app.services.conversation import ConversationService
from app.services.resource_usage import groups_sharing, shared_with_group
from app.services.sandbox_connection import SandboxConnectionService
from app.services.sandbox_workspace import (
    NOT_BROWSABLE,
    SandboxWorkspaceService,
    WorkspaceContents,
)
from app.services.sharing import SharingService

logger = logging.getLogger(__name__)


def project_path(path: str) -> str:
    """A path inside a project's container, as a person may name one.

    Relative to the container's working directory and inside it, never in a
    directory the platform keeps for itself. A leading `/` names the project's
    own root: a stored project lists its files as `/reports/q3.pdf`, and that
    is the path a person removes it by.

    Raises:
        BadRequestError: For a path that leaves the directory, or one in a
            directory the platform keeps.
    """
    cleaned = path.strip().strip("/")
    normal = posixpath.normpath(cleaned) if cleaned else ""
    if not normal or normal == "." or normal.startswith(".."):
        raise BadRequestError(
            message="Name a path inside the project, such as reports/q3.pdf",
            details={"path": path},
        )
    if _in_platform_folder(normal):
        raise BadRequestError(
            message="That folder is the platform's own; choose another name",
            details={"path": path},
        )
    return normal


def _in_platform_folder(path: str) -> bool:
    """Whether a path, however it is spelled, is in a folder the platform keeps.

    Resolved against the root first, so `a/../.agenticos/x` and `/.agenticos/x`
    are the folder they name.
    """
    normal = posixpath.normpath(f"/{path.strip()}").lstrip("/")
    reserved = tuple(prefix.strip("/") for prefix in NOT_BROWSABLE)
    return any(normal == prefix or normal.startswith(f"{prefix}/") for prefix in reserved)


class ProjectService:
    """Projects: who may see and change them, their chats and their files."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.workspaces = SandboxWorkspaceService(db)

    async def get(
        self, ctx: AuthContext, project_id: UUID, *, perm: Perm = Perm.PROJECTS_VIEW
    ) -> Project:
        """One project, when the caller may `perm` it.

        Raises:
            NotFoundError: If there is no such project or the caller may not see it.
            AuthorizationError: If the caller sees it and may not `perm` it.
        """
        project = await project_repo.get(self.db, project_id, organization_id=ctx.organization_id)
        missing = NotFoundError(message="Project not found", details={"project_id": project_id})
        if project is None or not await resolve_access(
            self.db, ctx, project, Perm.PROJECTS_VIEW, resource_type=PROJECT
        ):
            # Whether a private project exists is itself not the caller's to learn.
            raise missing
        if perm is not Perm.PROJECTS_VIEW and not await resolve_access(
            self.db, ctx, project, perm, resource_type=PROJECT
        ):
            raise AuthorizationError(
                message=(
                    "You can see this project but not change it"
                    if perm is Perm.PROJECTS_EDIT
                    else "You can see this project but not work in it"
                ),
                details={"project_id": project_id},
            )
        return project

    async def list_projects(
        self,
        ctx: AuthContext,
        *,
        search: str | None = None,
        group_id: UUID | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> ProjectList:
        """A page of the projects the caller may see, most recently changed first."""
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=PROJECT, perm=Perm.PROJECTS_VIEW
        )
        items, total = await project_repo.list_visible(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=shared is None,
            shared_ids=[] if shared is None else shared,
            search=search,
            only_ids=await shared_with_group(
                self.db, ctx, resource_type=PROJECT, group_id=group_id
            ),
            skip=skip,
            limit=limit,
        )
        return ProjectList(items=await self._read_many(ctx, items), total=total)

    async def read(self, ctx: AuthContext, project: Project) -> ProjectRead:
        """One project as the API shows it, with what the caller may do with it."""
        (read,) = await self._read_many(ctx, [project])
        return read

    async def _read_many(self, ctx: AuthContext, projects: list[Project]) -> list[ProjectRead]:
        ids = [project.id for project in projects]
        activity = await project_repo.chat_activity(
            self.db,
            organization_id=ctx.organization_id,
            project_ids=ids,
        )
        groups = await groups_sharing(self.db, ctx, resource_type=PROJECT, resource_ids=ids)
        usable = await accessible_ids(
            self.db, ctx, projects, Perm.PROJECTS_USE, resource_type=PROJECT
        )
        editable = await accessible_ids(
            self.db, ctx, projects, Perm.PROJECTS_EDIT, resource_type=PROJECT
        )
        agents = await agent_repo.get_many(
            self.db,
            [project.default_agent_id for project in projects if project.default_agent_id],
            organization_id=ctx.organization_id,
        )
        # Runnable, not merely visible: the chat starts with the default agent,
        # and one the reader may only look at answered their first message with
        # a refusal after the turn was already saved.
        runnable_agents = await accessible_ids(
            self.db, ctx, list(agents.values()), Perm.AGENTS_RUN, resource_type=AGENT
        )
        # And one that still answers at all: a default archived, unpublished or
        # switched off since it was set is offered no more than one never allowed.
        runnable_agents = await self._answering(
            [agent for agent in agents.values() if agent.id in runnable_agents]
        )
        reads = []
        for project in projects:
            count, last = activity.get(project.id, (0, None))
            agent = agents.get(project.default_agent_id) if project.default_agent_id else None
            seen = agent if agent is not None and agent.id in runnable_agents else None
            reads.append(
                ProjectRead.model_validate(project).model_copy(
                    update={
                        "chat_count": count,
                        "last_active_at": last,
                        "shared_groups": groups[project.id],
                        "can_use": project.id in usable,
                        "can_edit": project.id in editable,
                        # Both or neither: an agent the reader may not run is not
                        # named, and its id is not handed over either.
                        "default_agent_id": seen.id if seen else None,
                        "default_agent_name": seen.name if seen else None,
                    }
                )
            )
        return reads

    async def create(self, ctx: AuthContext, data: ProjectCreate) -> Project:
        """Create a project, in a container when this organization has a sandbox.

        Raises:
            BadRequestError: For a default agent the caller may not run, or an
                audience that is not this organization's.
        """
        if data.default_agent_id is not None:
            await self._check_default_agent(ctx, data.default_agent_id)
        # A container where the organization has a sandbox to run one on, files
        # the platform keeps where it has none; decided now, so the project does
        # not change what it is because somebody registered a host later - and on
        # that host, so a new organization default does not open it an empty one.
        connection = await SandboxConnectionService(self.db).ensure_local_connection(
            ctx.organization_id
        )
        narrowed = bool(data.group_ids or data.user_ids)
        project = await project_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            owner_user_id=ctx.user_id,
            name=data.name,
            description=data.description,
            instructions=data.instructions,
            default_agent_id=data.default_agent_id,
            backend="service" if connection is not None else "state",
            visibility="private" if narrowed else data.visibility.value,
            sandbox_connection_id=connection.id if connection is not None else None,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="project.created",
            target_type="project",
            target_id=str(project.id),
            details={"name": project.name, "backend": project.backend},
        )
        if narrowed:
            await SharingService(self.db).restrict_to(
                ctx,
                project,
                resource_type=PROJECT,
                group_ids=data.group_ids,
                user_ids=data.user_ids,
            )
        return project

    async def update(self, ctx: AuthContext, project_id: UUID, data: ProjectUpdate) -> Project:
        """Change a project's name, instructions, default agent or runtime."""
        project = await self.get(ctx, project_id, perm=Perm.PROJECTS_EDIT)
        update_data = writable(data, over=Project)
        if update_data.get("default_agent_id") is not None:
            await self._check_default_agent(ctx, update_data["default_agent_id"])
        if update_data.get("runtime", project.runtime) != project.runtime:
            await self._check_runtime_change(ctx, project)
        updated = await project_repo.update(self.db, project=project, update_data=update_data)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="project.updated",
            target_type="project",
            target_id=str(project.id),
            details={"fields": sorted(update_data)},
        )
        return updated

    async def delete(self, ctx: AuthContext, project_id: UUID) -> None:
        """Delete a project and its files; its chats stay, as ordinary chats."""
        project = await self.get(ctx, project_id, perm=Perm.PROJECTS_EDIT)
        await self.workspaces.purge_project(ctx, project)
        # The chats that go with it take their attachments and offloaded media.
        await ConversationService(self.db).forget_stored_files(
            ctx.organization_id, await project_repo.ownerless_chat_ids(self.db, project=project)
        )
        await project_repo.detach_conversations(self.db, project=project)
        await resource_grant_repo.delete_for_resource(
            self.db,
            organization_id=ctx.organization_id,
            resource_type=PROJECT.key,
            resource_id=project.id,
        )
        await project_repo.delete(self.db, project)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="project.deleted",
            target_type="project",
            target_id=str(project_id),
            details={"name": project.name},
        )

    async def for_run(self, ctx: AuthContext, conversation_id: UUID | None) -> Project | None:
        """The project a run works in, if its conversation is in one.

        Checked as the person the run is for: a chat started in a project they
        have since lost does not keep reaching its files.

        Raises:
            AuthorizationError: If the conversation is in a project this run's
                caller may no longer work in.
        """
        if conversation_id is None:
            return None
        conversation = await conversation_repo.get_conversation_by_id(self.db, conversation_id)
        if (
            conversation is None
            or conversation.organization_id != ctx.organization_id
            or conversation.project_id is None
        ):
            return None
        project = await project_repo.get(
            self.db, conversation.project_id, organization_id=ctx.organization_id
        )
        if project is None:
            return None
        if not await resolve_access(
            self.db, ctx, project, Perm.PROJECTS_USE, resource_type=PROJECT
        ):
            raise AuthorizationError(
                message="This chat is in a project you can no longer work in",
                details={"project_id": project.id},
            )
        return project

    async def check_can_start(self, ctx: AuthContext, project_id: UUID) -> Project:
        """The project a new chat is to start in, when the caller may work in it."""
        return await self.get(ctx, project_id, perm=Perm.PROJECTS_USE)

    async def chats(
        self, ctx: AuthContext, project_id: UUID, *, skip: int, limit: int
    ) -> tuple[list[Conversation], int]:
        """A page of the project's chats, whoever started them - for whoever may see it."""
        await self.get(ctx, project_id)
        return await ConversationService(self.db).list_project_chats(
            project_id,
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            skip=skip,
            limit=limit,
        )

    async def files(
        self, ctx: AuthContext, project_id: UUID
    ) -> tuple[Project, AgentWorkspace | None, WorkspaceContents]:
        """What the project's container holds, without starting it."""
        project = await self.get(ctx, project_id)
        listed = await self.workspaces.project_files(ctx, project)
        if listed is None:
            return project, None, WorkspaceContents(entries=[])
        row, contents = listed
        return project, row, contents

    async def file_bytes(self, ctx: AuthContext, project_id: UUID, *, path: str) -> bytes:
        """One file of the project, as its file browser lists it.

        Raises:
            NotFoundError: For no such file - and for one in a folder the platform
                keeps, a coding agent's session among them, which the browser
                never lists and a reader cannot fetch by naming it.
        """
        project = await self.get(ctx, project_id)
        if _in_platform_folder(path):
            raise NotFoundError(message="No such file", details={"path": path})
        return await self.workspaces.project_bytes(ctx, project, path=path)

    async def add_file(self, ctx: AuthContext, project_id: UUID, *, path: str, data: bytes) -> str:
        """Put a file in the project's container, where every agent in it finds it.

        Raises:
            BadRequestError: For a path outside the project, or a file over the
                upload limit.
        """
        project = await self.get(ctx, project_id, perm=Perm.PROJECTS_USE)
        target = project_path(path)
        limit = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if len(data) > limit:
            raise BadRequestError(
                message=f"A file in a project may be up to {settings.MAX_UPLOAD_SIZE_MB} MB",
                details={"path": target, "size": len(data)},
            )
        opened = await self.workspaces.open_project(ctx, project)
        try:
            parent = posixpath.dirname(target)
            if parent:
                await opened.workspace.make_dir(parent)
            await opened.workspace.write_bytes(target, data)
        finally:
            await self.workspaces.close(opened)
        await self._touched(ctx, project, "project.file_added", target)
        return target

    async def add_folder(self, ctx: AuthContext, project_id: UUID, *, path: str) -> str:
        project = await self.get(ctx, project_id, perm=Perm.PROJECTS_USE)
        target = project_path(path)
        opened = await self.workspaces.open_project(ctx, project)
        try:
            await opened.workspace.make_dir(target)
        finally:
            await self.workspaces.close(opened)
        await self._touched(ctx, project, "project.folder_added", target)
        return target

    async def remove(self, ctx: AuthContext, project_id: UUID, *, path: str) -> None:
        """Remove a file or a folder, with everything in it, from the project."""
        project = await self.get(ctx, project_id, perm=Perm.PROJECTS_USE)
        target = project_path(path)
        opened = await self.workspaces.open_project(ctx, project)
        try:
            if opened.kind == "state":
                await opened.workspace.remove(target)
            else:
                # The shell, for a folder with files in it; argv, so the path is a
                # word and never a command.
                result = await opened.workspace.run(["rm", "-rf", "--", target], timeout=60)
                if result.exit_code != 0:
                    # A folder an agent made read-only, say: the file is still
                    # there, so neither the answer nor the audit may say it went.
                    logger.warning(
                        "project_remove_refused",
                        extra={"project_id": str(project.id), "output": result.stderr},
                    )
                    raise BadRequestError(
                        message="The project's container would not remove this - "
                        "an agent may have made it read-only",
                        details={"path": target},
                    )
        finally:
            await self.workspaces.close(opened)
        await self._touched(ctx, project, "project.file_removed", target)

    async def _touched(self, ctx: AuthContext, project: Project, action: str, path: str) -> None:
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action=action,
            target_type="project",
            target_id=str(project.id),
            details={"path": path},
        )

    async def _check_runtime_change(self, ctx: AuthContext, project: Project) -> None:
        """Refuse a new runtime once the project's container exists.

        A container keeps the runtime it was started on - a run reattaches it -
        so the new one would be claimed, and briefed to agents, while their
        commands still ran in the old environment.
        """
        opened = await agent_workspace_repo.list_for_project(
            self.db, organization_id=ctx.organization_id, project_id=project.id
        )
        if any(row.session_id for row in opened):
            raise refused_field(
                "runtime",
                "This project's container is already running on its runtime, which cannot "
                "change - start a new project for another one",
            )

    async def _answering(self, agents: list[Agent]) -> set[UUID]:
        """Those a chat started with gets an answer from: published, not archived,
        and not an assistant its organization switched off."""
        published = [
            agent.id
            for agent in agents
            if agent.status != AgentStatus.ARCHIVED.value and agent.current_version_id is not None
        ]
        return set(published) - await organization_assistant_repo.switched_off(self.db, published)

    async def _check_default_agent(self, ctx: AuthContext, agent_id: UUID) -> None:
        """One the setter may run, and that runs at all: a new chat starts with it,
        and a draft or an archived agent refused that chat's first message."""
        agent = await agent_repo.get(self.db, agent_id, organization_id=ctx.organization_id)
        if agent is None or not await resolve_access(
            self.db, ctx, agent, Perm.AGENTS_RUN, resource_type=AGENT
        ):
            raise refused_field("default_agent_id", "Choose a default agent you can run")
        if agent.id not in await self._answering([agent]):
            raise refused_field(
                "default_agent_id",
                "Choose a published agent, not one archived or switched off - a new chat "
                "starts with it",
            )
