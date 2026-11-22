"""Current authorized personal state, shared by every proactive read and its final fence."""

from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import JsonValue, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.memory_keys import person_owner_key
from app.core.permissions import AuthContext, Perm
from app.db.models.user import User
from app.repositories import (
    channel_bot_repo,
    mcp_connection_repo,
    memory_repo,
    suggestion_repo,
)
from app.repositories import memory_claim as claim_repo
from app.repositories import personal_context as context_repo
from app.schemas.personal_context import ContextPacket
from app.services.agent_registry import AgentRegistryService
from app.services.conversation import ConversationService
from app.services.project import ProjectService
from app.services.tasks import TaskService

_JSON = TypeAdapter(dict[str, JsonValue])


def json_record(value: object) -> dict[str, JsonValue]:
    record = _JSON.validate_python(value)
    truncated = False

    def bound(item: JsonValue) -> JsonValue:
        nonlocal truncated
        if isinstance(item, str) and len(item) > 2000:
            truncated = True
            return item[:2000]
        if isinstance(item, list):
            return [bound(child) for child in item]
        if isinstance(item, dict):
            return {key: bound(child) for key, child in item.items()}
        return item

    result = {key: bound(item) for key, item in record.items()}
    if truncated:
        result["text_truncated"] = True
    return result


async def current_packet(
    db: AsyncSession, ctx: AuthContext, user: User, *, now: datetime, starter_id: UUID
) -> ContextPacket:
    """Read existing resources only. Missing lists remain explicitly incomplete."""
    assert ctx.user_id is not None
    project_page = await ProjectService(db).list_projects(ctx, skip=0, limit=100)
    projects = [
        json_record(
            item.model_dump(mode="json", include={"id", "name", "description", "updated_at"})
        )
        for item in project_page.items
    ]
    agent_rows, agent_total = await AgentRegistryService(db).list_agents(ctx, skip=0, limit=100)
    agents = [
        json_record(
            item.model_dump(
                mode="json", include={"id", "name", "description", "status", "updated_at"}
            )
        )
        for item in agent_rows
    ]
    # Routine access is checked by the trigger service, rather than treating all
    # organization triggers as the person's own automation.
    from app.services.agent_trigger import AgentTriggerService

    routine_rows, routine_total = await AgentTriggerService(db).list_for_organization(
        ctx, skip=0, limit=100
    )
    routines = [
        json_record(
            row.model_dump(
                mode="json",
                include={
                    "id",
                    "name",
                    "prompt",
                    "enabled",
                    "agent_id",
                    "created_by_user_id",
                    "cron_expression",
                    "timezone",
                    "activation_status",
                    "last_fired_at",
                },
            )
        )
        for row in routine_rows
    ]
    routines_complete = len(routine_rows) >= routine_total
    tasks: list[dict[str, JsonValue]] = []
    boards: list[dict[str, JsonValue]] = []
    tasks_complete = True
    task_service = TaskService(db)
    visible_boards = await task_service.boards(ctx)
    visible_boards.sort(key=lambda board: board.scope_kind != "private")
    for board in visible_boards[:20]:
        private = board.scope_kind == "private" and board.scope_id == ctx.user_id
        boards.append(json_record(board.model_dump(mode="json")))
        if len(tasks) >= 100:
            tasks_complete = False
            break
        page = await task_service.list_tasks(ctx, board.table_id, skip=0, limit=100)
        tasks.extend(
            json_record({**task.model_dump(mode="json"), "owner_user_id": str(ctx.user_id)})
            for task in page.items
            if private or task.assignee_user_id == ctx.user_id
        )
        tasks_complete = tasks_complete and not page.has_more and len(tasks) <= 100
        tasks = tasks[:100]
    tasks_complete = tasks_complete and len(visible_boards) <= 20
    local_day = now.astimezone(ZoneInfo(user.time_zone or "UTC")).date()
    due_state = {
        str(task["id"]): (
            "overdue"
            if datetime.fromisoformat(str(task["due_at"]))
            .astimezone(ZoneInfo(user.time_zone or "UTC"))
            .date()
            < local_day
            else "today"
        )
        for task in tasks
        if task.get("due_at")
        and task.get("status") not in {"done", "cancelled"}
        and datetime.fromisoformat(str(task["due_at"]))
        .astimezone(ZoneInfo(user.time_zone or "UTC"))
        .date()
        <= local_day
    }
    owner = person_owner_key(ctx.user_id)
    notes = await memory_repo.list_for_owner(
        db, organization_id=ctx.organization_id, agent_id=starter_id, owner_key=owner, limit=20
    )
    claims = await claim_repo.list_in_scopes(
        db,
        organization_id=ctx.organization_id,
        scopes=[claim_repo.ClaimScope(owner), claim_repo.ClaimScope(owner, starter_id)],
        in_effect=True,
        limit=20,
    )
    memory = [
        json_record(
            {
                "id": str(note.id),
                "name": note.name,
                "statement": note.content[:2000],
                "scope": "person",
            }
        )
        for note in notes
    ]
    memory.extend(
        json_record(
            {
                "id": str(claim.id),
                "statement": claim.statement[:2000],
                "subject": claim.subject,
                "scope": "profile" if claim.agent_id is None else "starter",
            }
        )
        for claim in claims
    )
    history = await suggestion_repo.list_all(
        db, organization_id=ctx.organization_id, user_id=ctx.user_id, limit=200
    )
    connections, _ = await mcp_connection_repo.list_for_user(
        db, user_id=ctx.user_id, enabled_only=True
    )
    bots = await channel_bot_repo.list_for_org(db, organization_id=ctx.organization_id, limit=100)
    services = sorted(
        {connection.name for connection in connections}
        | {bot.platform for bot in bots if bot.is_active}
    )
    questions = await ConversationService(db).list_waiting_questions(ctx, skip=0, limit=100)
    return ContextPacket(
        as_of=now,
        subject_id=str(ctx.user_id),
        audience="private",
        profile=json_record(
            {
                "name": user.full_name,
                "role": user.job_title,
                "about": user.about,
                "language": user.locale,
                "time_zone": user.time_zone,
                "working_hours": user.working_hours,
            }
        ),
        messages=[],
        memory=memory,
        tool_receipts=[],
        changed_source_ids=[],
        current_state=json_record(
            {
                "projects": projects,
                "projects_complete": len(projects) >= project_page.total,
                "agents": agents,
                "agents_complete": len(agents) >= agent_total,
                "routines": routines,
                "deleted_resources": await context_repo.removed_resources(
                    db, organization_id=ctx.organization_id, user_id=ctx.user_id
                ),
                "routines_complete": routines_complete,
                "tasks": tasks,
                "due_state": due_state,
                "task_boards": boards,
                "tasks_complete": tasks_complete,
                "memory_complete": len(notes) < 20 and len(claims) < 20,
                "text_excerpt_limit": 2000,
                "connected_services": services,
                "feature_usage": await context_repo.usage(
                    db,
                    organization_id=ctx.organization_id,
                    user_id=ctx.user_id,
                    time_zone=user.time_zone or "UTC",
                ),
                "pending_questions": [
                    question.model_dump(mode="json") for question in questions.items
                ],
                "prior_decisions": [
                    {
                        "identity": row.payload.get("intent"),
                        "title": row.title,
                        "status": row.status,
                        "request": row.payload.get("chat_prompt"),
                    }
                    for row in history
                    if row.status != "open"
                ],
                "existing_inbox": [
                    {
                        "id": str(row.id),
                        "title": row.title,
                        "detail": row.detail,
                        "intent": row.payload.get("intent"),
                    }
                    for row in history
                    if row.status == "open"
                    and (not row.payload.get("personal_context") or row.outcome_id is not None)
                ],
            }
        ),
        available_features=[
            json_record({"id": key, "available": ctx.has(perm), "usage": "unknown"})
            for key, perm in (
                ("projects", Perm.PROJECTS_VIEW),
                ("tasks", Perm.TABLES_VIEW),
                ("tables", Perm.TABLES_VIEW),
                ("evals", Perm.DATASETS_RUN),
                ("agents", Perm.AGENTS_VIEW),
                ("workflows", Perm.WORKFLOWS_VIEW),
                ("skills", Perm.SKILLS_VIEW),
                ("context", Perm.CONTEXT_VIEW),
                ("knowledge", Perm.COLLECTIONS_VIEW),
                ("apps", Perm.ARTIFACTS_VIEW),
                ("mcp", Perm.MCP_MANAGE),
            )
        ],
    )
