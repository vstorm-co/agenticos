"""Install reviewed work state and an ordinary agent routine inside a project."""

import hashlib
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, PlatformMcpServerRef
from app.agents.table_bindings import TableGrant
from app.core.audit import current_impersonator, record_audit
from app.core.exceptions import AuthorizationError, BadRequestError, ConflictError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.project import Project
from app.db.models.project_tracking import ProjectTracking
from app.repositories import agent_trigger_repo
from app.repositories import project_tracking as tracking_repo
from app.schemas.agent_trigger import TriggerCreate
from app.schemas.project_tracking import (
    ProjectTrackingCreate,
    ProjectTrackingRead,
    ProjectTrackingReview,
)
from app.services.agent_registry import AgentRegistryService
from app.services.agent_trigger import AgentTriggerService
from app.services.project import ProjectService
from app.services.routine_sources import RoutineSourceService, RoutineSourceSnapshot, read_policy
from app.services.virtual_tables import VirtualTableService


@dataclass(frozen=True)
class _Reviewed:
    spec: AgentSpec
    name: str
    sources: RoutineSourceSnapshot


def _with_task_table(spec: AgentSpec, table_id: UUID, *, name: str) -> AgentSpec:
    grants = [grant for grant in spec.table_bindings if grant.table_id != table_id]
    grant = TableGrant.model_validate(
        {"table_id": table_id, "operations": ["read", "create", "update"]}
    )
    if len(grants) >= 50:
        raise BadRequestError(message="Choose an agent with room for the project task table")
    table_tools = [
        "list_virtual_tables",
        "get_virtual_table",
        "query_virtual_table",
        "get_virtual_table_record",
        "add_virtual_table_record",
        "update_virtual_table_record",
    ]
    servers = [
        server.model_copy(
            update={"allowed_tools": list(dict.fromkeys([*server.allowed_tools, *table_tools]))}
        )
        if isinstance(server, PlatformMcpServerRef) and server.allowed_tools is not None
        else server
        for server in spec.mcp_servers
    ]
    if not any(isinstance(server, PlatformMcpServerRef) for server in servers):
        servers.append(PlatformMcpServerRef(account="platform", allowed_tools=table_tools))
    return spec.model_copy(
        update={
            "name": name,
            "table_bindings": [*grants, grant],
            "mcp_servers": servers,
        }
    )


class ProjectTrackingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.projects = ProjectService(db)
        self.agents = AgentRegistryService(db)
        self.sources = RoutineSourceService(db)

    @staticmethod
    def _console(ctx: AuthContext) -> None:
        if (
            ctx.user_id is None
            or ctx.api_key_id is not None
            or ctx.routine_id is not None
            or ctx.fired_as_creator is not None
            or ctx.subject_is_publisher_fallback
            or current_impersonator() is not None
        ):
            raise AuthorizationError(
                message="Set up project tracking from your own console session"
            )

    @staticmethod
    def _can_create(ctx: AuthContext) -> None:
        if not ctx.has(Perm.AGENTS_EDIT) or not ctx.has(Perm.TABLES_CREATE):
            raise AuthorizationError(
                message="Creating a project tracker requires creating agents and tables"
            )

    async def _review(
        self, ctx: AuthContext, project: Project, agent_id: UUID, version_id: UUID
    ) -> _Reviewed:
        self._can_create(ctx)
        agent = await self.agents.get(ctx, agent_id, perm=Perm.AGENTS_EDIT)
        _, spec, _ = await self.agents.get_pinned_spec(ctx, agent_id, version_id)
        preview = AgentTrigger(
            id=uuid4(),
            organization_id=ctx.organization_id,
            agent_id=agent_id,
            project_id=project.id,
            created_by_user_id=ctx.subject_id,
            pinned_version_id=version_id,
            runs_as_creator=True,
            event_config={},
            answer_to="run_log",
        )
        return _Reviewed(
            spec=spec, name=agent.name, sources=await self.sources.snapshot(ctx, preview)
        )

    async def review(
        self, ctx: AuthContext, project_id: UUID, *, agent_id: UUID, version_id: UUID
    ) -> ProjectTrackingReview:
        self._console(ctx)
        project = await self.projects.get(ctx, project_id, perm=Perm.PROJECTS_USE)
        reviewed = await self._review(ctx, project, agent_id, version_id)
        return ProjectTrackingReview(
            review_token=reviewed.sources.token(),
            base_agent_id=agent_id,
            base_version_id=version_id,
            base_agent_name=reviewed.name,
            resources=reviewed.sources.resources,
            accounts=reviewed.sources.accounts,
            unavailable_sources=reviewed.sources.unavailable,
        )

    async def _read(self, ctx: AuthContext, row: ProjectTracking) -> ProjectTrackingRead:
        trigger = await agent_trigger_repo.get(
            self.db, row.trigger_id, organization_id=ctx.organization_id
        )
        if trigger is None:
            raise NotFoundError(message="The project tracker no longer exists")
        return ProjectTrackingRead(
            id=row.id,
            project_id=row.project_id,
            agent_id=row.agent_id,
            agent_version_id=row.agent_version_id,
            table_id=row.table_id,
            trigger_id=row.trigger_id,
            conversation_id=trigger.conversation_id,
        )

    async def get(self, ctx: AuthContext, project_id: UUID) -> ProjectTrackingRead | None:
        self._console(ctx)
        await self.projects.get(ctx, project_id, perm=Perm.PROJECTS_USE)
        row = await tracking_repo.get(
            self.db,
            organization_id=ctx.organization_id,
            project_id=project_id,
            user_id=ctx.subject_id,
        )
        return None if row is None else await self._read(ctx, row)

    async def create(
        self, ctx: AuthContext, project_id: UUID, data: ProjectTrackingCreate
    ) -> ProjectTrackingRead:
        self._console(ctx)
        project = await self.projects.get(ctx, project_id, perm=Perm.PROJECTS_USE)
        fingerprint = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
        existing = await tracking_repo.get(
            self.db,
            organization_id=ctx.organization_id,
            project_id=project_id,
            user_id=ctx.subject_id,
        )
        if existing is not None:
            if existing.request_hash != fingerprint:
                raise ConflictError(
                    message="This project already has your tracker. Manage its existing routine and task table."
                )
            return await self._read(ctx, existing)
        reviewed = await self._review(ctx, project, data.base_agent_id, data.base_version_id)
        if reviewed.sources.unavailable or reviewed.sources.token() != data.source_review_token:
            raise ConflictError(
                message="The project's sources changed. Review them again before publishing the tracker."
            )
        from app.schemas.task import BoardEnsure
        from app.schemas.virtual_table import TableUpdate
        from app.services.tasks import TaskService

        board = await TaskService(self.db).ensure_board(
            ctx, BoardEnsure(scope="project", scope_id=project.id)
        )
        table = await VirtualTableService(self.db).describe_table(ctx, board.table_id)
        if table.archived_at is not None:
            raise ConflictError(
                message="This project's task board is archived. Restore it before "
                "publishing the tracker.",
                details={"table_id": table.id},
            )
        # The explicit preset's name also names the project's one shared task board, when
        # this caller may rename it; otherwise the board keeps the name it has.
        if table.name != data.table_name and table.can_manage:
            table = await VirtualTableService(self.db).update_table(
                ctx, table.id, TableUpdate(name=data.table_name)
            )
        spec = _with_task_table(reviewed.spec, table.id, name=data.agent_name)
        agent = await self.agents.create(ctx, spec, choose_model=False)
        version = await self.agents.publish(
            ctx, agent.id, note="Publish the explicitly reviewed project-tracking preset"
        )
        trigger = await AgentTriggerService(self.db).create(
            ctx,
            agent.id,
            TriggerCreate(
                name=f"Keep {project.name[:90]} on track",
                project_id=project.id,
                pinned_version_id=version.id,
                runs_as_creator=True,
                interval_seconds=data.interval_seconds,
                answer_to="run_log",
                prompt=(
                    f"Keep this project on track using task table {table.id}. Read its current records first. "
                    "Use only the explicitly reviewed project sources to verify progress, owners, blockers and due dates. "
                    "Use the Person and Agent relations, Next step for the current actor, and Notes for rich-text context. Do not switch Next step to Agent unless execution was explicitly requested; an agent reference may identify who prepared work while a person reviews it. "
                    "Update task state and next actions only from evidence. Compare due dates and waiting deadlines with the current time; "
                    "do not invent replies or completed actions. Leave missing evidence visible as a blocker. "
                    "Report actionable changes and upcoming or missed deadlines in this project conversation. "
                    "External follow-ups still require their ordinary authorization; do not send them just because a task is overdue."
                ),
            ),
        )
        admitted = read_policy(trigger.approved_sources)
        expected = reviewed.sources.policy
        if (
            admitted.secret_sources != expected.secret_sources
            or admitted.phone_sources != expected.phone_sources
            or admitted.mcp_sources != expected.mcp_sources
            or admitted.project_id != expected.project_id
            or admitted.external_sources != expected.external_sources
            or admitted.project_hash != expected.project_hash
            or admitted.root_mcp_ids != expected.root_mcp_ids
        ):
            raise ConflictError(message="A source changed during setup. Review the tracker again.")
        row = await tracking_repo.create(
            self.db,
            tracking=ProjectTracking(
                organization_id=ctx.organization_id,
                project_id=project.id,
                user_id=ctx.subject_id,
                agent_id=agent.id,
                agent_version_id=version.id,
                table_id=table.id,
                trigger_id=trigger.id,
                request_hash=fingerprint,
            ),
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="project.tracking_created",
            target_type="project",
            target_id=str(project.id),
            details={
                "agent_id": str(agent.id),
                "table_id": str(table.id),
                "trigger_id": str(trigger.id),
            },
        )
        return await self._read(ctx, row)
