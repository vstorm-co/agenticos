"""Task boards exercise real table revisions, live audiences and durable wakeups."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.group import Group, GroupMember
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.task_board import TaskBoard, TaskLink
from app.db.models.user import User
from app.schemas.task import BoardEnsure, TaskCreate, TaskUpdate
from app.schemas.virtual_table import ColumnInput, RecordUpdate, SchemaUpdate, TableUpdate
from app.services.task_execution import TaskExecution
from app.services.tasks import TaskLifecycle, TaskService
from app.services.virtual_tables import VirtualTableService
from app.worker.jobs import WakeTask

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@dataclass
class World:
    org: Organization
    users: list[User]
    contexts: list[AuthContext]


async def world(db: AsyncSession) -> World:
    users = [
        User(email=f"{uuid4()}@example.com", hashed_password="x", full_name=name)
        for name in ("Owner", "Other")
    ]
    db.add_all(users)
    await db.flush()
    org = Organization(name="Tasks", slug=f"tasks-{uuid4().hex}", created_by_user_id=users[0].id)
    db.add(org)
    await db.flush()
    db.add_all(
        [
            OrganizationMember(organization_id=org.id, user_id=user.id, role="owner")
            for user in users
        ]
    )
    await db.flush()
    return World(
        org,
        users,
        [
            AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.OWNER)
            for user in users
        ],
    )


async def test_private_board_is_reused_and_hidden_even_from_another_org_owner(
    db: AsyncSession,
) -> None:
    data = await world(db)
    service = TaskService(db)
    first = await service.ensure_board(data.contexts[0], BoardEnsure())
    second = await service.ensure_board(data.contexts[0], BoardEnsure())
    assert first.id == second.id
    assert await db.scalar(select(func.count()).select_from(TaskBoard)) == 1
    tables = VirtualTableService(db)
    assert (await tables.list_tables(data.contexts[1])).items == []
    with pytest.raises(NotFoundError):
        await tables.describe_table(data.contexts[1], first.table_id)
    assert len((await tables.list_tables(data.contexts[0])).items) == 1


async def test_group_membership_controls_table_and_task_access_live(db: AsyncSession) -> None:
    data = await world(db)
    group = Group(organization_id=data.org.id, name="Support", created_by_user_id=data.users[0].id)
    db.add(group)
    await db.flush()
    members = [GroupMember(group_id=group.id, user_id=user.id) for user in data.users]
    db.add_all(members)
    await db.flush()
    service = TaskService(db)
    task = await service.create(
        data.contexts[0], TaskCreate(title="Check the reply", scope="group", scope_id=group.id)
    )
    assert (await service.get(data.contexts[1], task.id)).id == task.id
    assert len((await VirtualTableService(db).list_tables(data.contexts[1])).items) == 1
    await db.delete(members[1])
    await db.flush()
    with pytest.raises(NotFoundError):
        await service.get(data.contexts[1], task.id)
    assert (await VirtualTableService(db).list_tables(data.contexts[1])).items == []


async def test_generic_table_writes_enforce_task_contract_and_revision(db: AsyncSession) -> None:
    data = await world(db)
    service = TaskService(db)
    task = await service.create(data.contexts[0], TaskCreate(title="Prepare draft"))
    board = await service.ensure_board(data.contexts[0], BoardEnsure())
    tables = VirtualTableService(db)
    await tables.update_record(
        data.contexts[0],
        board.table_id,
        task.id,
        RecordUpdate(
            expected_revision=task.revision,
            values={board.column_ids["status"]: board.status_ids["done"]},
        ),
    )
    assert (await service.get(data.contexts[0], task.id)).status == "done"
    current = await tables.describe_table(data.contexts[0], board.table_id)
    columns = [
        ColumnInput.model_validate(column.model_dump(exclude={"revision"}))
        for column in current.columns
    ]
    columns[0].type = "long_text"
    with pytest.raises(BadRequestError, match="Task fields"):
        await tables.update_schema(
            data.contexts[0],
            board.table_id,
            SchemaUpdate(expected_version=current.schema_version, columns=columns),
        )


async def test_editing_or_completing_task_invalidates_old_reminder(db: AsyncSession) -> None:
    data = await world(db)
    service = TaskService(db)
    task = await service.create(
        data.contexts[0],
        TaskCreate(title="Send draft", start_at=datetime.now(UTC) + timedelta(days=1)),
    )
    old = WakeTask(organization_id=data.org.id, task_id=task.id, revision=task.revision)
    task = await service.update(
        data.contexts[0],
        task.id,
        TaskUpdate(
            title="Send revised draft",
            start_at=datetime.now(UTC) + timedelta(days=2),
            expected_revision=task.revision,
        ),
    )
    await TaskExecution(db).wake(old)
    assert (await service.get(data.contexts[0], task.id)).status == "planned"
    assert (await db.get(TaskLink, task.id)).outcome_id is None
    task = await service.update(
        data.contexts[0],
        task.id,
        TaskUpdate(title=task.title, status="done", expected_revision=task.revision),
    )
    await TaskExecution(db).wake(
        WakeTask(organization_id=data.org.id, task_id=task.id, revision=task.revision)
    )
    assert (await service.get(data.contexts[0], task.id)).status == "done"


async def test_human_reminder_reuses_one_case_and_completion_propagates_both_ways(
    db: AsyncSession,
) -> None:
    from app.db.models.outcome import Outcome
    from app.services.outcome import OutcomeService

    data = await world(db)
    service = TaskService(db)
    task = await service.create(
        data.contexts[0],
        TaskCreate(title="Send approved draft", start_at=datetime.now(UTC) - timedelta(minutes=1)),
    )
    wake = WakeTask(organization_id=data.org.id, task_id=task.id, revision=task.revision)
    await TaskExecution(db).wake(wake)
    await TaskExecution(db).wake(wake)
    current = await service.get(data.contexts[0], task.id)
    assert current.status == "waiting_for_user" and current.outcome_id is not None
    assert await db.scalar(select(func.count()).select_from(Outcome)) == 1
    await OutcomeService(db).settle(data.contexts[0], current.outcome_id, "acknowledge", via="chat")
    assert (await service.get(data.contexts[0], task.id)).status == "waiting_for_user"
    await OutcomeService(db).settle(data.contexts[0], current.outcome_id, "resolve", via="chat")
    assert (await service.get(data.contexts[0], task.id)).status == "done"


async def test_rescheduling_reminder_reopens_the_same_case(db: AsyncSession) -> None:
    from app.db.models.outcome import Outcome

    data = await world(db)
    service = TaskService(db)
    task = await service.create(
        data.contexts[0],
        TaskCreate(title="Review draft", start_at=datetime.now(UTC) - timedelta(minutes=1)),
    )
    await TaskExecution(db).wake(
        WakeTask(organization_id=data.org.id, task_id=task.id, revision=task.revision)
    )
    first = await service.get(data.contexts[0], task.id)
    assert first.outcome_id is not None
    scheduled = await service.update(
        data.contexts[0],
        task.id,
        TaskUpdate(
            title=first.title,
            status="planned",
            start_at=datetime.now(UTC) - timedelta(seconds=1),
            expected_revision=first.revision,
        ),
    )
    assert scheduled.status == "planned"
    assert scheduled.outcome_id == first.outcome_id
    assert (await db.get(Outcome, first.outcome_id)).status == "resolved"
    await TaskExecution(db).wake(
        WakeTask(organization_id=data.org.id, task_id=task.id, revision=scheduled.revision)
    )
    reopened = await service.get(data.contexts[0], task.id)
    assert reopened.status == "waiting_for_user"
    assert reopened.outcome_id == first.outcome_id
    assert (await db.get(Outcome, first.outcome_id)).status == "open"
    assert await db.scalar(select(func.count()).select_from(Outcome)) == 1


@pytest.mark.parametrize("delay", [0, 300])
@pytest.mark.parametrize("scope", ["private", "project"])
@pytest.mark.parametrize("terminal_status", ["completed", "failed"])
async def test_agent_task_is_pinned_and_ends_in_review_or_blocked_state(
    db: AsyncSession,
    delay: int,
    scope: str,
    terminal_status: str,
) -> None:
    from app.agents.spec import AgentSpec
    from app.db.models.agent import Agent, AgentVersion
    from app.db.models.agent_trigger import AgentTrigger
    from app.repositories import agent_run_repo
    from app.services.agent_trigger import AgentTriggerService

    data = await world(db)
    agent = Agent(
        organization_id=data.org.id,
        name="Researcher",
        slug=f"research-{uuid4().hex}",
        owner_user_id=data.users[0].id,
    )
    db.add(agent)
    await db.flush()
    spec = AgentSpec(
        name="Researcher", instructions="Prepare a draft, never send it without authorization."
    )
    version = AgentVersion(
        organization_id=data.org.id, agent_id=agent.id, version=1, spec=spec.model_dump(mode="json")
    )
    db.add(version)
    await db.flush()
    agent.current_version_id = version.id
    agent.status = "published"
    await db.flush()
    from app.db.models.conversation import Conversation
    from app.db.models.project import Project

    project = Project(organization_id=data.org.id, owner_user_id=data.users[0].id, name="Launch")
    db.add(project)
    await db.flush()
    service = TaskService(db)
    task = await service.create(
        data.contexts[0],
        TaskCreate(
            scope=scope,
            scope_id=project.id if scope == "project" else None,
            title="Prepare reply",
            assignee_agent_id=agent.id,
            start_at=datetime.now(UTC) + timedelta(seconds=delay - 1),
        ),
    )
    from app.services.agent_registry import AgentRegistryService

    registry = AgentRegistryService(db)
    with pytest.raises(BadRequestError, match="still has scheduled task work"):
        await registry.delete(data.contexts[0], agent.id)
    assert await db.get(Agent, agent.id) is agent
    link = await db.get(TaskLink, task.id)
    assert link is not None and link.trigger_id is not None and task.conversation_id is not None
    working = await db.get(Conversation, task.conversation_id)
    assert working.project_id == (project.id if scope == "project" else None)
    trigger = await db.get(AgentTrigger, link.trigger_id)
    assert trigger is not None and trigger.one_shot and trigger.pinned_version_id == version.id
    triggers = AgentTriggerService(db)
    if delay:
        assert (
            len(await triggers.claim_and_advance(now=datetime.now(UTC) + timedelta(minutes=6))) == 1
        )
    else:
        assert trigger.next_fire_at is None
        assert await triggers.claim_and_advance(now=datetime.now(UTC)) == []
    assert trigger.next_fire_at is None and trigger.is_active
    assert await triggers.claim_and_advance(now=datetime.now(UTC) + timedelta(days=1)) == []
    assert (await triggers.list_for_organization(data.contexts[0]))[0] == []
    run = await agent_run_repo.create_run(
        db,
        organization_id=data.org.id,
        agent_id=agent.id,
        agent_version_id=version.id,
        user_id=data.users[0].id,
        conversation_id=task.conversation_id,
        surface="web",
        model_label="test",
        started_at=datetime.now(UTC),
    )
    assert await TaskExecution(db).started(data.contexts[0], trigger)
    assert (await service.get(data.contexts[0], task.id)).status == "in_progress"
    for pending_status in ("running", "awaiting_approval", "awaiting_answer"):
        run.status = pending_status
        await TaskExecution(db).finished(trigger, run)
        assert trigger.is_active
        assert (await service.get(data.contexts[0], task.id)).status == "in_progress"
    run.status = terminal_status
    await db.flush()
    await TaskExecution(db).finished(trigger, run)
    current = await service.get(data.contexts[0], task.id)
    assert current.status == ("waiting_for_user" if terminal_status == "completed" else "blocked")
    assert current.outcome_id is not None
    assert not trigger.is_active
    await registry.delete(data.contexts[0], agent.id)
    assert await db.get(Agent, agent.id) is None


async def test_project_and_organization_scopes_are_reused_without_implicit_cross_tenant_access(
    db: AsyncSession,
) -> None:
    from dataclasses import replace

    from app.db.models.project import Project

    data = await world(db)
    project = Project(
        organization_id=data.org.id, owner_user_id=data.users[0].id, name="Launch", backend="state"
    )
    db.add(project)
    await db.flush()
    service = TaskService(db)
    board = await service.ensure_board(
        data.contexts[0], BoardEnsure(scope="project", scope_id=project.id)
    )
    assert (
        await service.ensure_board(
            data.contexts[1], BoardEnsure(scope="project", scope_id=project.id)
        )
    ).id == board.id
    assert (await service.boards(data.contexts[0]))[0].scope_name == "Launch"
    org_board = await service.ensure_board(data.contexts[0], BoardEnsure(scope="organization"))
    assert (
        await service.ensure_board(data.contexts[1], BoardEnsure(scope="organization"))
    ).id == org_board.id
    with pytest.raises(NotFoundError):
        await service.ensure_board(
            replace(data.contexts[0], organization_id=uuid4()),
            BoardEnsure(scope="project", scope_id=project.id),
        )
    with pytest.raises(NotFoundError):
        await service.ensure_board(data.contexts[0], BoardEnsure(scope="group", scope_id=uuid4()))


async def test_overlapping_members_get_one_group_board(db: AsyncSession) -> None:
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    data = await world(db)
    group = Group(organization_id=data.org.id, name="Delivery")
    db.add(group)
    await db.flush()
    db.add_all([GroupMember(group_id=group.id, user_id=user.id) for user in data.users])
    await db.commit()
    sessions = async_sessionmaker(db.bind, expire_on_commit=False)

    async def open_board(ctx: AuthContext):
        async with sessions() as session, session.begin():
            return await TaskService(session).ensure_board(
                ctx, BoardEnsure(scope="group", scope_id=group.id)
            )

    first, second = await asyncio.gather(*(open_board(ctx) for ctx in data.contexts))
    assert first.id == second.id and first.table_id == second.table_id
    assert await db.scalar(select(func.count()).select_from(TaskBoard)) == 1


async def test_done_or_deleted_task_clears_inbox_and_withdraws_pending_wakeups(
    db: AsyncSession,
) -> None:
    from app.db.models.background_job import BackgroundJob
    from app.db.models.outcome import Outcome
    from app.db.models.suggestion import Suggestion

    data = await world(db)
    service = TaskService(db)
    task = await service.create(
        data.contexts[0],
        TaskCreate(title="Check invoice", start_at=datetime.now(UTC) - timedelta(minutes=1)),
    )
    await TaskExecution(db).wake(
        WakeTask(organization_id=data.org.id, task_id=task.id, revision=task.revision)
    )
    task = await service.get(data.contexts[0], task.id)
    assert task.outcome_id is not None
    await service.update(
        data.contexts[0],
        task.id,
        TaskUpdate(title=task.title, status="done", expected_revision=task.revision),
    )
    assert (await db.get(Outcome, task.outcome_id)).status == "resolved"
    assert (
        await db.scalar(select(Suggestion).where(Suggestion.outcome_id == task.outcome_id))
    ).status == "accepted"
    assert (
        await db.scalar(
            select(func.count())
            .select_from(BackgroundJob)
            .where(BackgroundJob.kind == "wake-task", BackgroundJob.status == "queued")
        )
        == 0
    )
    other = await service.create(
        data.contexts[0],
        TaskCreate(
            title="Check another invoice", start_at=datetime.now(UTC) - timedelta(minutes=1)
        ),
    )
    await TaskExecution(db).wake(
        WakeTask(organization_id=data.org.id, task_id=other.id, revision=other.revision)
    )
    other = await service.get(data.contexts[0], other.id)
    await VirtualTableService(db).delete_record(
        data.contexts[0], other.table_id, other.id, expected_revision=other.revision
    )
    assert (await db.get(Outcome, other.outcome_id)).status == "resolved"
    with pytest.raises(NotFoundError):
        await service.get(data.contexts[0], other.id)


async def test_a_removed_group_reviewer_cannot_complete_the_shared_task(db: AsyncSession) -> None:
    from app.db.models.outcome import Outcome
    from app.services.outcome import OutcomeService

    data = await world(db)
    group = Group(organization_id=data.org.id, name="Reviews")
    db.add(group)
    await db.flush()
    membership = [GroupMember(group_id=group.id, user_id=user.id) for user in data.users]
    db.add_all(membership)
    await db.flush()
    service = TaskService(db)
    task = await service.create(
        data.contexts[0],
        TaskCreate(
            title="Review the invoice",
            scope="group",
            scope_id=group.id,
            assignee_user_id=data.users[1].id,
            start_at=datetime.now(UTC) - timedelta(minutes=1),
        ),
    )
    await TaskExecution(db).wake(
        WakeTask(organization_id=data.org.id, task_id=task.id, revision=task.revision)
    )
    link = await db.get(TaskLink, task.id)
    old_case = link.outcome_id
    await db.delete(membership[1])
    await db.flush()
    await OutcomeService(db).settle(data.contexts[1], old_case, "resolve", via="inbox")
    assert (await service.get(data.contexts[0], task.id)).status == "blocked"
    assert (await db.get(Outcome, old_case)).status == "resolved"
    assert (await db.get(Outcome, link.outcome_id)).user_id == data.users[0].id


async def test_handoff_moves_attention_without_leaking_the_previous_owners_private_chat(
    db: AsyncSession,
) -> None:
    from app.db.models.conversation import Conversation
    from app.db.models.outcome import Outcome

    data = await world(db)
    group = Group(organization_id=data.org.id, name="Finance")
    chat = Conversation(
        organization_id=data.org.id, user_id=data.users[0].id, title="Private source"
    )
    db.add_all([group, chat])
    await db.flush()
    db.add_all([GroupMember(group_id=group.id, user_id=user.id) for user in data.users])
    await db.flush()
    service = TaskService(db)
    task = await service.create(
        data.contexts[0],
        TaskCreate(
            title="Review the shared notes",
            scope="group",
            scope_id=group.id,
            assignee_user_id=data.users[1].id,
            start_at=datetime.now(UTC) - timedelta(minutes=1),
            conversation_id=chat.id,
        ),
    )
    await TaskExecution(db).wake(
        WakeTask(organization_id=data.org.id, task_id=task.id, revision=task.revision)
    )
    link = await db.get(TaskLink, task.id)
    old_case = link.outcome_id
    assert (await db.get(Outcome, old_case)).source_conversation_id is None
    task = await service.get(data.contexts[0], task.id)
    await service.update(
        data.contexts[0],
        task.id,
        TaskUpdate(
            title=task.title,
            status="waiting_for_user",
            assignee_user_id=data.users[0].id,
            expected_revision=task.revision,
        ),
    )
    assert (await db.get(Outcome, old_case)).status == "resolved"
    new_case = await db.get(Outcome, link.outcome_id)
    assert new_case.user_id == data.users[0].id and new_case.source_conversation_id == chat.id


async def test_restoring_a_muted_task_case_reopens_the_task_without_replaying_notifications(
    db: AsyncSession,
) -> None:
    from app.db.models.notification import Notification
    from app.db.models.suggestion import Suggestion
    from app.services.outcome import OutcomeService
    from app.services.suggestions import SuggestionService

    data = await world(db)
    service = TaskService(db)
    task = await service.create(
        data.contexts[0],
        TaskCreate(title="Check the draft", start_at=datetime.now(UTC) - timedelta(minutes=1)),
    )
    await TaskExecution(db).wake(
        WakeTask(organization_id=data.org.id, task_id=task.id, revision=task.revision)
    )
    task = await service.get(data.contexts[0], task.id)
    await OutcomeService(db).settle(data.contexts[0], task.outcome_id, "mute", via="inbox")
    assert (await service.get(data.contexts[0], task.id)).status == "cancelled"
    finding = await db.scalar(select(Suggestion).where(Suggestion.outcome_id == task.outcome_id))
    count = await db.scalar(select(func.count()).select_from(Notification))
    await SuggestionService(db).restore(data.contexts[0], finding.id)
    restored = await service.get(data.contexts[0], task.id)
    assert restored.status == "waiting_for_user" and restored.outcome_id == task.outcome_id
    assert await db.scalar(select(func.count()).select_from(Notification)) == count


async def test_personal_chat_can_create_project_tasks_without_linking_its_private_transcript(
    db: AsyncSession,
) -> None:
    from dataclasses import replace

    from app.db.models.conversation import Conversation
    from app.db.models.project import Project

    data = await world(db)
    personal = Conversation(
        organization_id=data.org.id, user_id=data.users[0].id, title="Personal chat"
    )
    project = Project(
        organization_id=data.org.id, owner_user_id=data.users[0].id, name="Launch", backend="state"
    )
    db.add_all([personal, project])
    await db.flush()
    ctx = replace(data.contexts[0], source_conversation_id=personal.id)
    service = TaskService(db)
    task = await service.create(
        ctx, TaskCreate(scope="project", scope_id=project.id, title="Prepare report")
    )
    assert task.scope == "project" and task.scope_id == project.id
    assert task.conversation_id is None
    # An explicit link to an incompatible transcript remains a refusal.
    with pytest.raises(BadRequestError, match="task's project"):
        await service.create(
            ctx,
            TaskCreate(
                scope="project",
                scope_id=project.id,
                title="Wrong link",
                conversation_id=personal.id,
            ),
        )


async def test_group_membership_does_not_grant_a_viewer_table_writes(db: AsyncSession) -> None:
    from app.db.models.resource_grant import ResourceGrant
    from app.schemas.virtual_table import RecordCreate

    data = await world(db)
    group = Group(organization_id=data.org.id, name="Reviews")
    db.add(group)
    await db.flush()
    members = [GroupMember(group_id=group.id, user_id=user.id) for user in data.users]
    db.add_all(members)
    await db.flush()
    service = TaskService(db)
    task = await service.create(
        data.contexts[0], TaskCreate(title="Review", scope="group", scope_id=group.id)
    )
    viewer = AuthContext(
        user_id=data.users[1].id, organization_id=data.org.id, role=OrgRoleName.VIEWER
    )
    tables = VirtualTableService(db)
    board = await db.get(TaskBoard, task.board_id)
    assert (await service.get(viewer, task.id)).id == task.id
    with pytest.raises(NotFoundError):
        await tables.create_record(
            viewer, task.table_id, RecordCreate(values={board.column_ids["title"]: "Injected"})
        )
    with pytest.raises(NotFoundError):
        await tables.update_record(
            viewer,
            task.table_id,
            task.id,
            RecordUpdate(
                values={board.column_ids["title"]: "Changed"}, expected_revision=task.revision
            ),
        )
    with pytest.raises(NotFoundError):
        await tables.delete_record(viewer, task.table_id, task.id, expected_revision=task.revision)
    db.add(
        ResourceGrant(
            organization_id=data.org.id,
            resource_type="table",
            resource_id=task.table_id,
            subject_user_id=viewer.user_id,
            level="edit",
        )
    )
    await db.flush()
    await tables.update_record(
        viewer,
        task.table_id,
        task.id,
        RecordUpdate(
            values={board.column_ids["title"]: "Explicitly shared"}, expected_revision=task.revision
        ),
    )
    assert (await service.get(viewer, task.id)).title == "Explicitly shared"
    await db.delete(members[1])
    await db.flush()
    with pytest.raises(NotFoundError):
        await service.get(viewer, task.id)


@pytest.mark.parametrize("lost_membership", ["group", "organization"])
async def test_a_reminder_notifies_its_creator_when_the_assignee_loses_access(
    db: AsyncSession, lost_membership: str
) -> None:
    from app.db.models.outcome import Outcome

    data = await world(db)
    group = Group(organization_id=data.org.id, name="Reviews")
    db.add(group)
    await db.flush()
    members = [GroupMember(group_id=group.id, user_id=user.id) for user in data.users]
    db.add_all(members)
    await db.flush()
    service = TaskService(db)
    task = await service.create(
        data.contexts[0],
        TaskCreate(
            title="Review",
            scope="group",
            scope_id=group.id,
            assignee_user_id=data.users[1].id,
            start_at=datetime.now(UTC) - timedelta(minutes=1),
        ),
    )
    removed = (
        members[1]
        if lost_membership == "group"
        else await db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == data.org.id,
                OrganizationMember.user_id == data.users[1].id,
            )
        )
    )
    await db.delete(removed)
    await db.flush()
    await TaskExecution(db).wake(
        WakeTask(organization_id=data.org.id, task_id=task.id, revision=task.revision)
    )
    current = await service.get(data.contexts[0], task.id)
    link = await db.get(TaskLink, task.id)
    case = await db.get(Outcome, link.outcome_id)
    assert current.status == "blocked" and case.user_id == data.users[0].id
    from app.db.models.suggestion import Suggestion

    finding = await db.scalar(select(Suggestion).where(Suggestion.outcome_id == case.id))
    assert "no longer has access" in finding.detail


async def test_project_use_does_not_grant_operator_table_edits(db: AsyncSession) -> None:
    from app.core.permissions import Perm
    from app.db.models.project import Project
    from app.db.models.resource_grant import ResourceGrant
    from app.schemas.virtual_table import RecordCreate

    data = await world(db)
    project = Project(
        organization_id=data.org.id,
        owner_user_id=data.users[0].id,
        name="Shared",
        visibility="org",
        backend="state",
    )
    db.add(project)
    await db.flush()
    service = TaskService(db)
    task = await service.create(
        data.contexts[0], TaskCreate(scope="project", scope_id=project.id, title="Review")
    )
    operator = AuthContext(
        user_id=data.users[1].id, organization_id=data.org.id, role=OrgRoleName.OPERATOR
    )
    assert operator.has(Perm.PROJECTS_USE) and not operator.has(Perm.TABLES_EDIT)
    assert (await service.get(operator, task.id)).id == task.id
    table = await db.get(TaskBoard, task.board_id)
    tables = VirtualTableService(db)
    with pytest.raises(NotFoundError):
        await tables.create_record(
            operator, task.table_id, RecordCreate(values={table.column_ids["title"]: "Injected"})
        )
    with pytest.raises(NotFoundError):
        await tables.update_record(
            operator,
            task.table_id,
            task.id,
            RecordUpdate(
                values={table.column_ids["title"]: "Changed"}, expected_revision=task.revision
            ),
        )
    with pytest.raises(NotFoundError):
        await tables.delete_record(
            operator, task.table_id, task.id, expected_revision=task.revision
        )
    db.add(
        ResourceGrant(
            organization_id=data.org.id,
            resource_type="table",
            resource_id=task.table_id,
            subject_user_id=operator.user_id,
            level="edit",
        )
    )
    await db.flush()
    changed = await tables.update_record(
        operator,
        task.table_id,
        task.id,
        RecordUpdate(
            values={table.column_ids["title"]: "Authorized"}, expected_revision=task.revision
        ),
    )
    assert changed.record.id == task.id


@pytest.mark.parametrize("kind", ["private", "project", "group"])
async def test_removing_scope_purges_managed_table_and_cancels_its_wakeups(
    db: AsyncSession, kind: str
) -> None:
    from app.db.models.background_job import BackgroundJob
    from app.db.models.project import Project
    from app.db.models.virtual_table import VirtualTable, VirtualTableRecord
    from app.services.group import GroupService
    from app.services.personal_data import PersonalDataService
    from app.services.project import ProjectService

    data = await world(db)
    scope_id = data.users[0].id
    if kind == "project":
        project = Project(
            organization_id=data.org.id,
            owner_user_id=data.users[0].id,
            name="Delete me",
            backend="state",
        )
        db.add(project)
        await db.flush()
        scope_id = project.id
    elif kind == "group":
        group = Group(organization_id=data.org.id, name="Delete me")
        db.add(group)
        await db.flush()
        db.add(GroupMember(group_id=group.id, user_id=data.users[0].id))
        scope_id = group.id
        await db.flush()
    service = TaskService(db)
    other = await service.ensure_board(data.contexts[1], BoardEnsure())
    task = await service.create(
        data.contexts[0],
        TaskCreate(
            scope=kind,
            scope_id=scope_id,
            title="Reminder",
            start_at=datetime.now(UTC) + timedelta(days=1),
        ),
    )
    review = await service.create(
        data.contexts[0],
        TaskCreate(
            scope=kind, scope_id=scope_id, title="Pending review", status="waiting_for_user"
        ),
    )
    review_link = await db.get(TaskLink, review.id)
    case_id = review_link.outcome_id
    board_id, table_id = task.board_id, task.table_id
    if kind == "project":
        await ProjectService(db).delete(data.contexts[0], scope_id)
    elif kind == "group":
        await GroupService(db).delete(data.contexts[0], scope_id)
    else:
        await PersonalDataService(db).purge(scope_id)
    from app.db.models.outcome import Outcome

    assert (await db.get(Outcome, case_id)).status == "resolved"
    assert await db.scalar(select(TaskBoard).where(TaskBoard.id == board_id)) is None
    assert await db.scalar(select(VirtualTable).where(VirtualTable.id == table_id)) is None
    assert (
        await db.scalar(select(VirtualTableRecord).where(VirtualTableRecord.table_id == table_id))
        is None
    )
    jobs = list(
        await db.scalars(
            select(BackgroundJob).where(
                BackgroundJob.kind == "wake-task",
                BackgroundJob.payload["task_id"].astext == str(task.id),
            )
        )
    )
    assert jobs and all(job.status == "cancelled" for job in jobs)
    assert (
        await db.scalar(select(VirtualTable).where(VirtualTable.id == other.table_id)) is not None
    )


async def test_scope_teardown_disables_its_agent_and_cancels_queued_fire(db: AsyncSession) -> None:
    from app.agents.spec import AgentSpec
    from app.db.models.agent import Agent, AgentVersion
    from app.db.models.agent_trigger import AgentTrigger
    from app.db.models.background_job import BackgroundJob
    from app.db.models.project import Project

    data = await world(db)
    agent = Agent(
        organization_id=data.org.id,
        owner_user_id=data.users[0].id,
        name="Worker",
        slug=f"worker-{uuid4().hex}",
    )
    project = Project(organization_id=data.org.id, owner_user_id=data.users[0].id, name="Tasks")
    db.add_all([agent, project])
    await db.flush()
    version = AgentVersion(
        organization_id=data.org.id,
        agent_id=agent.id,
        version=1,
        spec=AgentSpec(name="Worker").model_dump(mode="json"),
    )
    db.add(version)
    await db.flush()
    agent.current_version_id, agent.status = version.id, "published"
    service = TaskService(db)
    task = await service.create(
        data.contexts[0],
        TaskCreate(
            scope="project",
            scope_id=project.id,
            title="Work",
            next_actor="agent",
            assignee_agent_id=agent.id,
        ),
    )
    link = await db.get(TaskLink, task.id)
    trigger_id = link.trigger_id
    assert trigger_id is not None
    await service.purge_scope("project", project.id, organization_id=data.org.id)
    trigger = await db.get(AgentTrigger, trigger_id)
    assert trigger is not None and not trigger.is_active
    jobs = list(
        await db.scalars(
            select(BackgroundJob).where(
                BackgroundJob.kind == "fire-trigger",
                BackgroundJob.payload["trigger_id"].astext == str(trigger_id),
            )
        )
    )
    assert jobs and all(job.status == "cancelled" for job in jobs)


async def test_a_reminder_from_a_departed_creator_becomes_blocked_for_its_reviewer(
    db: AsyncSession,
) -> None:
    from sqlalchemy import delete

    from app.db.models.outcome import Outcome

    data = await world(db)
    service = TaskService(db)
    task = await service.create(
        data.contexts[0],
        TaskCreate(
            scope="organization",
            scope_id=data.org.id,
            title="Take over reminder",
            assignee_user_id=data.users[1].id,
            start_at=datetime.now(UTC) - timedelta(minutes=1),
        ),
    )
    await db.execute(
        delete(OrganizationMember).where(
            OrganizationMember.organization_id == data.org.id,
            OrganizationMember.user_id == data.users[0].id,
        )
    )
    await TaskExecution(db).wake(
        WakeTask(organization_id=data.org.id, task_id=task.id, revision=task.revision)
    )
    current = await service.get(data.contexts[1], task.id)
    assert current.status == "blocked"
    link = await db.get(TaskLink, task.id)
    assert link is not None
    case = await db.get(Outcome, link.outcome_id)
    assert case is not None and case.user_id == data.users[1].id and case.status == "open"


async def test_a_detached_task_trigger_cannot_execute(db: AsyncSession) -> None:
    from app.services.task_access import execution_allows

    data = await world(db)
    assert not await execution_allows(db, data.contexts[0], uuid4())


async def test_cancelling_a_task_expires_its_parked_approval(db: AsyncSession) -> None:
    from app.agents.spec import AgentSpec
    from app.db.models.agent import Agent, AgentVersion
    from app.db.models.agent_run import ToolApproval
    from app.repositories import agent_run_repo

    data = await world(db)
    agent = Agent(
        organization_id=data.org.id,
        owner_user_id=data.users[0].id,
        name="Worker",
        slug=f"worker-{uuid4().hex}",
    )
    db.add(agent)
    await db.flush()
    version = AgentVersion(
        organization_id=data.org.id,
        agent_id=agent.id,
        version=1,
        spec=AgentSpec(name="Worker").model_dump(mode="json"),
    )
    db.add(version)
    await db.flush()
    agent.current_version_id, agent.status = version.id, "published"
    service = TaskService(db)
    task = await service.create(
        data.contexts[0], TaskCreate(title="Paused task", assignee_agent_id=agent.id)
    )
    link = await db.get(TaskLink, task.id)
    assert link is not None and link.trigger_id is not None
    run = await agent_run_repo.create_run(
        db,
        organization_id=data.org.id,
        agent_id=agent.id,
        agent_version_id=version.id,
        user_id=data.users[0].id,
        conversation_id=task.conversation_id,
        surface="schedule",
        model_label="test",
        started_at=datetime.now(UTC),
        trigger_id=link.trigger_id,
    )
    run.status = "awaiting_approval"
    run.paused_state = {"messages": [], "tool_call_ids": {}}
    approval = ToolApproval(
        organization_id=data.org.id, run_id=run.id, agent_id=agent.id, tool_id="write", tool_args={}
    )
    db.add(approval)
    await db.flush()
    await service.update(
        data.contexts[0],
        task.id,
        TaskUpdate(title=task.title, status="cancelled", expected_revision=task.revision),
    )
    assert run.status == "cancelled" and run.paused_state is None
    assert approval.status == "expired"
    assert link.trigger_id is None


async def test_deletion_fence_blocks_a_concurrent_trigger_assignment(
    db: AsyncSession, engine
) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models.agent import Agent
    from app.db.models.agent_trigger import AgentTrigger
    from app.repositories import agent_repo

    data = await world(db)
    agent = Agent(
        organization_id=data.org.id,
        owner_user_id=data.users[0].id,
        name="Deleting",
        slug=f"deleting-{uuid4().hex}",
    )
    db.add(agent)
    await db.commit()
    await agent_repo.fence_deletion(db, agent.id, organization_id=data.org.id)
    async with async_sessionmaker(engine)() as assignment:
        await assignment.execute(text("SET LOCAL lock_timeout = '200ms'"))
        assignment.add(
            AgentTrigger(
                organization_id=data.org.id,
                agent_id=agent.id,
                created_by_user_id=data.users[0].id,
                prompt="Task",
                interval_seconds=3600,
                next_fire_at=datetime.now(UTC),
            )
        )
        with pytest.raises(DBAPIError) as refused:
            await assignment.flush()
        assert refused.value.orig.sqlstate == "55P03"


async def test_a_read_only_member_cannot_be_assigned_an_actionable_task(db: AsyncSession) -> None:
    data = await world(db)
    membership = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == data.org.id,
            OrganizationMember.user_id == data.users[1].id,
        )
    )
    assert membership is not None
    membership.role = "viewer"
    await db.flush()
    with pytest.raises(BadRequestError, match="Choose a person"):
        await TaskService(db).create(
            data.contexts[0],
            TaskCreate(
                scope="organization",
                scope_id=data.org.id,
                title="Review",
                assignee_user_id=data.users[1].id,
                status="waiting_for_user",
            ),
        )


async def test_a_reminder_blocks_when_its_creator_loses_group_access(db: AsyncSession) -> None:
    data = await world(db)
    group = Group(organization_id=data.org.id, name="Shared")
    db.add(group)
    await db.flush()
    owner = GroupMember(group_id=group.id, user_id=data.users[0].id)
    db.add_all([owner, GroupMember(group_id=group.id, user_id=data.users[1].id)])
    await db.flush()
    service = TaskService(db)
    task = await service.create(
        data.contexts[0],
        TaskCreate(
            title="Review handoff",
            scope="group",
            scope_id=group.id,
            assignee_user_id=data.users[1].id,
            start_at=datetime.now(UTC) - timedelta(seconds=1),
        ),
    )
    await db.delete(owner)
    await db.flush()
    await TaskExecution(db).wake(
        WakeTask(organization_id=data.org.id, task_id=task.id, revision=task.revision)
    )
    assert (await service.get(data.contexts[1], task.id)).status == "blocked"
    link = await db.get(TaskLink, task.id)
    assert link is not None and link.outcome_id is not None


@pytest.mark.parametrize("field", ["status", "next_actor"])
async def test_managed_task_lifecycle_choices_cannot_be_removed_via_generic_schema_editor(
    db: AsyncSession, field: str
) -> None:
    data = await world(db)
    board = await TaskService(db).ensure_board(data.contexts[0], BoardEnsure())
    tables = VirtualTableService(db)
    current = await tables.describe_table(data.contexts[0], board.table_id)
    columns = [
        ColumnInput.model_validate(column.model_dump(exclude={"revision"}))
        for column in current.columns
    ]
    selected = next(column for column in columns if str(column.id) == board.column_ids[field])
    selected.options = selected.options[:-1]
    with pytest.raises(BadRequestError, match=r"Task states|next-step choices"):
        await tables.update_schema(
            data.contexts[0],
            board.table_id,
            SchemaUpdate(expected_version=current.schema_version, columns=columns),
        )


async def test_task_listing_and_board_index_do_not_reveal_another_members_private_board(
    db: AsyncSession,
) -> None:
    data = await world(db)
    service = TaskService(db)
    mine = await service.ensure_board(data.contexts[0], BoardEnsure())
    other = await service.ensure_board(data.contexts[1], BoardEnsure())
    visible = await service.boards(data.contexts[0])
    assert [board.table_id for board in visible] == [mine.table_id]
    with pytest.raises(NotFoundError):
        await service.list_tasks(data.contexts[0], other.table_id)
    with pytest.raises(NotFoundError):
        await service.list_tasks(data.contexts[0], uuid4())


async def test_editing_only_a_reminder_deadline_requeues_the_current_record_revision(
    db: AsyncSession,
):
    from app.db.models.background_job import BackgroundJob

    data = await world(db)
    service = TaskService(db)
    start = datetime.now(UTC) + timedelta(hours=1)
    task = await service.create(data.contexts[0], TaskCreate(title="Review draft", start_at=start))
    updated = await service.update(
        data.contexts[0],
        task.id,
        TaskUpdate(
            title=task.title,
            start_at=start,
            due_at=start + timedelta(hours=2),
            expected_revision=task.revision,
        ),
    )
    jobs = list(
        await db.scalars(
            select(BackgroundJob).where(
                BackgroundJob.kind == "wake-task", BackgroundJob.status == "queued"
            )
        )
    )
    assert len(jobs) == 1
    assert jobs[0].payload["revision"] == updated.revision
    await TaskExecution(db).wake(
        WakeTask(organization_id=data.org.id, task_id=task.id, revision=task.revision)
    )
    assert (await service.get(data.contexts[0], task.id)).outcome_id is None


async def test_an_agent_task_cannot_mark_its_own_commitment_complete(db: AsyncSession):
    from dataclasses import replace

    from app.core.exceptions import AuthorizationError

    data = await world(db)
    task = await TaskService(db).create(data.contexts[0], TaskCreate(title="Needs human review"))
    link = await db.get(TaskLink, task.id)
    board = await db.get(TaskBoard, task.board_id)
    from app.db.models.virtual_table import VirtualTableRecord
    from app.schemas.task import TaskFields

    record = await db.get(VirtualTableRecord, task.id)
    link.trigger_id = uuid4()
    # The executing routine cannot use a tool write to close its own review obligation.
    with pytest.raises(AuthorizationError, match="cannot close"):
        await TaskExecution(db).changed(
            replace(data.contexts[0], routine_id=link.trigger_id),
            board,
            record,
            link,
            TaskFields(title=task.title, status="done"),
        )
    link.trigger_id = None
    assert (await TaskService(db).get(data.contexts[0], task.id)).status == "planned"


async def test_assignment_options_follow_live_board_audience(db: AsyncSession) -> None:
    data = await world(db)
    service = TaskService(db)
    private = await service.ensure_board(data.contexts[0], BoardEnsure())
    options = await service.assignee_options(data.contexts[0], private.table_id)
    assert options is not None
    assert [person.id for person in options] == [data.users[0].id]
    with pytest.raises(NotFoundError):
        await service.assignee_options(data.contexts[1], private.table_id)
    group = Group(organization_id=data.org.id, name="Eligible", created_by_user_id=data.users[0].id)
    db.add(group)
    await db.flush()
    membership = GroupMember(group_id=group.id, user_id=data.users[0].id)
    db.add(membership)
    await db.flush()
    board = await service.ensure_board(
        data.contexts[0], BoardEnsure(scope="group", scope_id=group.id)
    )
    options = await service.assignee_options(data.contexts[0], board.table_id)
    assert options is not None
    assert [person.id for person in options] == [data.users[0].id]
    db.add(GroupMember(group_id=group.id, user_id=data.users[1].id))
    await db.flush()
    options = await service.assignee_options(data.contexts[0], board.table_id)
    assert options is not None
    assert {person.id for person in options} == {user.id for user in data.users}
    await db.delete(membership)
    await db.flush()
    with pytest.raises(NotFoundError):
        await service.assignee_options(data.contexts[0], board.table_id)


async def test_restoring_a_board_rearms_a_reminder_consumed_during_archive(
    db: AsyncSession,
) -> None:
    from app.db.models.background_job import BackgroundJob

    data = await world(db)
    service = TaskService(db)
    reminder = await service.create(
        data.contexts[0],
        TaskCreate(title="Preserve reminder", start_at=datetime.now(UTC) - timedelta(minutes=1)),
    )
    tables = VirtualTableService(db)
    await tables.archive_table(data.contexts[0], reminder.table_id)
    payload = WakeTask(organization_id=data.org.id, task_id=reminder.id, revision=reminder.revision)
    await TaskExecution(db).wake(payload)
    link = await db.get(TaskLink, reminder.id)
    assert link is not None and link.outcome_id is None
    jobs = list(
        await db.scalars(
            select(BackgroundJob).where(
                BackgroundJob.kind == "wake-task",
                BackgroundJob.payload["task_id"].astext == str(reminder.id),
            )
        )
    )
    assert jobs
    for job in jobs:
        job.status = "succeeded"
    await db.flush()
    await tables.unarchive_table(data.contexts[0], reminder.table_id)
    queued = list(
        await db.scalars(
            select(BackgroundJob).where(
                BackgroundJob.kind == "wake-task",
                BackgroundJob.payload["task_id"].astext == str(reminder.id),
                BackgroundJob.status == "queued",
            )
        )
    )
    assert len(queued) == 1
    assert queued[0].payload["revision"] == reminder.revision
    await TaskExecution(db).wake(payload)
    assert (await service.get(data.contexts[0], reminder.id)).status == "waiting_for_user"
    assert link.outcome_id is not None


@pytest.mark.parametrize("change", ["person_removed", "scope_revoked"])
async def test_board_creation_rechecks_scope_after_serializing_admission(db, monkeypatch, change):
    from unittest.mock import AsyncMock

    from app.services import tasks

    data = await world(db)
    if change == "person_removed":
        monkeypatch.setattr(tasks.user_repo, "get_by_id", AsyncMock(return_value=None))
    else:
        monkeypatch.setattr(tasks, "scope_allows", AsyncMock(side_effect=[True, False]))
    with pytest.raises(NotFoundError):
        await TaskService(db).ensure_board(data.contexts[0], BoardEnsure())
    assert await db.scalar(select(func.count()).select_from(TaskBoard)) == 0


@pytest.mark.parametrize("change", ["missing", "tenant", "owner", "archived", "another_chat"])
async def test_tasks_cannot_link_an_unavailable_or_unrelated_private_conversation(db, change):
    from dataclasses import replace

    from app.core.exceptions import AuthorizationError
    from app.repositories import conversation_repo

    data = await world(db)
    ctx = data.contexts[0]
    service = TaskService(db)
    board = await service.ensure_board(ctx, BoardEnsure())
    conversation = await conversation_repo.create_conversation(
        db,
        title="Working",
        organization_id=data.org.id,
        user_id=data.users[1].id if change == "owner" else ctx.user_id,
    )
    if change == "tenant":
        other = await world(db)
        conversation.organization_id = other.org.id
    elif change == "archived":
        conversation.is_archived = True
    elif change == "another_chat":
        ctx = replace(ctx, source_conversation_id=uuid4())
    await db.flush()
    with pytest.raises((NotFoundError, AuthorizationError)):
        await service._conversation(ctx, board, uuid4() if change == "missing" else conversation.id)


async def test_generic_record_writes_reject_invalid_managed_task_fields(db):
    from app.repositories import task as task_repo
    from app.services import tasks

    data = await world(db)
    service = TaskService(db)
    task = await service.create(data.contexts[0], TaskCreate(title="Task"))
    record = await task_repo.record(db, task.id, data.org.id)
    assert record is not None
    board = await task_repo.for_table(db, record.table_id, data.org.id)
    assert board is not None
    record.values = {**record.values, board.column_ids["title"]: None}
    with pytest.raises(BadRequestError, match="Invalid task fields"):
        await tasks.TaskLifecycle(db).changed(data.contexts[0], record)


async def test_intact_managed_schema_remains_editable_and_missing_tables_cannot_list_tasks(db):
    data = await world(db)
    service = TaskService(db)
    board = await service.ensure_board(data.contexts[0], BoardEnsure())
    table = await service.tables.describe_table(data.contexts[0], board.table_id)
    await TaskLifecycle(db).protect_schema(data.contexts[0], board.table_id, table.columns)
    with pytest.raises(NotFoundError):
        await service.list_tasks(data.contexts[0], uuid4())


async def test_assignee_picker_reads_every_page_and_refuses_a_noneditable_managed_board(
    db, monkeypatch
):
    from unittest.mock import AsyncMock, MagicMock

    from app.services import access, tasks

    data = await world(db)
    ctx = data.contexts[0]
    service = TaskService(db)
    board = await service.ensure_board(ctx, BoardEnsure(scope="organization"))
    members = [
        (MagicMock(user_id=uuid4()), f"{i}@example.com", f"Person {i}", None, None)
        for i in range(101)
    ]
    listing = AsyncMock(side_effect=[members[:100], members[100:]])
    monkeypatch.setattr(tasks.member_repo, "list_for_org", listing)
    monkeypatch.setattr(access, "member_context", AsyncMock(return_value=ctx))
    assert len(await service.assignee_options(ctx, board.table_id)) == 101
    assert listing.await_args.kwargs["skip"] == 100
    monkeypatch.setattr(tasks, "board_allows", AsyncMock(return_value=False))
    with pytest.raises(NotFoundError):
        await service.assignee_options(ctx, board.table_id)
    monkeypatch.setattr(tasks.task_repo, "for_table", AsyncMock(return_value=None))
    assert await service.assignee_options(ctx, board.table_id) is None


@pytest.mark.parametrize("lost", ["created", "finding_first", "finding_last"])
async def test_missing_lifecycle_binding_is_an_explicit_failure_not_phantom_success(
    db, monkeypatch, lost
):
    from unittest.mock import AsyncMock

    from app.repositories import task as repo

    data = await world(db)
    service = TaskService(db)
    if lost == "created":
        monkeypatch.setattr(repo, "link", AsyncMock(return_value=None))
        with pytest.raises(RuntimeError, match="lifecycle"):
            await service.create(data.contexts[0], TaskCreate(title="Bound task"))
    else:
        task = await service.create(data.contexts[0], TaskCreate(title="Bound task"))
        link = await repo.link(db, task.id)
        service.create = AsyncMock(return_value=task)
        service.update = AsyncMock(return_value=task)
        monkeypatch.setattr(
            repo, "link", AsyncMock(side_effect=[None] if lost == "finding_first" else [link, None])
        )
        with pytest.raises(RuntimeError, match="no binding"):
            await service.finding(
                data.contexts[0],
                outcome_id=uuid4(),
                conversation_id=uuid4(),
                title=task.title,
                description=task.description,
            )


async def test_an_existing_task_binding_replaces_an_obsolete_attention_case(db, monkeypatch):
    from unittest.mock import AsyncMock

    from app.repositories import task as repo
    from app.services.outcome import OutcomeService

    data = await world(db)
    service = TaskService(db)
    task = await service.create(data.contexts[0], TaskCreate(title="Old title"))
    link = await repo.link(db, task.id)
    assert link is not None
    old = uuid4()
    # A source case is resolved through its service before its task is rebound.
    link.outcome_id = old
    service.create = AsyncMock(return_value=task)
    service.update = AsyncMock(return_value=task)
    service.get = AsyncMock(return_value=task)
    settle = AsyncMock()
    monkeypatch.setattr(OutcomeService, "resolve_task", settle)
    # Keep the link in memory: the replacement cases belong to the publisher's transaction.
    monkeypatch.setattr(repo, "flush", AsyncMock())
    monkeypatch.setattr(repo, "link", AsyncMock(return_value=link))
    await service.finding(
        data.contexts[0],
        outcome_id=uuid4(),
        conversation_id=None,
        title="New title",
        description="Updated draft",
    )
    settle.assert_awaited_once_with(old, organization_id=data.org.id)


async def test_concurrently_removed_board_cannot_update_or_purge_an_unrelated_table(
    db, monkeypatch
):
    from unittest.mock import AsyncMock

    from app.services import tasks

    data = await world(db)
    service = TaskService(db)
    task = await service.create(data.contexts[0], TaskCreate(title="Original task"))
    board = await tasks.task_repo.for_table(db, task.table_id, data.org.id)
    assert board is not None
    service.get = AsyncMock(return_value=task)
    monkeypatch.setattr(tasks.task_repo, "for_table", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError):
        await service.update(
            data.contexts[0], task.id, TaskUpdate(title="Changed", expected_revision=task.revision)
        )
    monkeypatch.setattr(tasks.task_repo, "in_scope", AsyncMock(return_value=[board]))
    monkeypatch.setattr(tasks.virtual_table_repo, "get_table", AsyncMock(return_value=None))
    purge = AsyncMock()
    monkeypatch.setattr(tasks.task_repo, "purge_table", purge)
    await service.purge_scope("private", data.users[0].id, organization_id=data.org.id)
    purge.assert_not_awaited()


async def _as_member(db: AsyncSession, data: World) -> AuthContext:
    member = await db.scalar(
        select(OrganizationMember).where(OrganizationMember.user_id == data.users[1].id)
    )
    assert member is not None
    member.role = "member"
    await db.flush()
    return AuthContext(user_id=data.users[1].id, organization_id=data.org.id, role="member")


async def test_a_member_works_on_the_organizations_board_but_cannot_change_it(
    db: AsyncSession,
) -> None:
    data = await world(db)
    member = await _as_member(db, data)
    service = TaskService(db)
    tables = VirtualTableService(db)
    opened = await service.open_board(member, BoardEnsure(scope="organization"))
    assert opened.can_edit is True

    seen = await tables.describe_table(member, opened.table_id)
    assert (seen.can_edit, seen.can_manage) == (True, False)
    with pytest.raises(AuthorizationError):
        await tables.archive_table(member, opened.table_id)
    with pytest.raises(AuthorizationError):
        await tables.update_table(member, opened.table_id, TableUpdate(name="Mine now"))
    with pytest.raises(AuthorizationError):
        await tables.update_schema(
            member,
            opened.table_id,
            SchemaUpdate(
                expected_version=seen.schema_version,
                columns=[
                    *[ColumnInput.model_validate(column.model_dump()) for column in seen.columns],
                    ColumnInput(label="Extra", type="text"),
                ],
            ),
        )
    task = await service.create(member, TaskCreate(title="Still mine to add", scope="organization"))
    assert task.table_id == opened.table_id
    assert (await tables.describe_table(member, opened.table_id)).archived_at is None


async def test_an_owner_archives_and_restores_the_organizations_board(db: AsyncSession) -> None:
    data = await world(db)
    owner = data.contexts[0]
    member = await _as_member(db, data)
    service = TaskService(db)
    tables = VirtualTableService(db)
    opened = await service.open_board(owner, BoardEnsure(scope="organization"))
    assert opened.can_edit is True
    assert (await tables.describe_table(owner, opened.table_id)).can_manage is True

    await tables.archive_table(owner, opened.table_id)
    assert (await tables.describe_table(member, opened.table_id)).can_restore is False
    with pytest.raises(AuthorizationError):
        await tables.unarchive_table(member, opened.table_id)
    restored = await tables.unarchive_table(owner, opened.table_id)
    assert restored.archived_at is None


async def test_a_group_lead_changes_the_groups_board(db: AsyncSession) -> None:
    data = await world(db)
    member = await _as_member(db, data)
    group = Group(organization_id=data.org.id, name="Ops")
    db.add(group)
    await db.flush()
    db.add(GroupMember(group_id=group.id, user_id=data.users[1].id, is_lead=True))
    await db.flush()
    tables = VirtualTableService(db)
    board = await TaskService(db).open_board(member, BoardEnsure(scope="group", scope_id=group.id))

    renamed = await tables.update_table(member, board.table_id, TableUpdate(name="Ops tasks"))

    assert renamed.name == "Ops tasks"


async def test_a_board_default_view_is_the_boards_to_change_whoever_saved_it(
    db: AsyncSession,
) -> None:
    from app.schemas.table_view import TableViewUpdate
    from app.services.virtual_tables import TableViewService

    data = await world(db)
    member = await _as_member(db, data)
    opened = await TaskService(db).open_board(member, BoardEnsure(scope="organization"))
    table = await VirtualTableService(db).describe_table(member, opened.table_id)
    assert table.default_view_id is not None
    views = TableViewService(db)

    seen = await views.get_view(member, opened.table_id, table.default_view_id)
    assert (seen.owner_user_id, seen.can_manage, seen.can_delete) == (
        data.users[1].id,
        False,
        False,
    )
    listed = await views.list_views(member, opened.table_id)
    assert not any(view.can_manage for view in listed.items if view.id == table.default_view_id)
    with pytest.raises(AuthorizationError):
        await views.update_view(
            member, opened.table_id, table.default_view_id, TableViewUpdate(name="Mine")
        )
    with pytest.raises(AuthorizationError):
        await views.delete_view(member, opened.table_id, table.default_view_id)

    renamed = await views.update_view(
        data.contexts[0], opened.table_id, table.default_view_id, TableViewUpdate(name="Ours")
    )
    assert renamed.name == "Ours"


async def test_a_group_lead_changes_the_board_default_view_someone_else_saved(
    db: AsyncSession,
) -> None:
    from app.schemas.table_view import TableViewUpdate
    from app.services.virtual_tables import TableViewService

    data = await world(db)
    lead = await _as_member(db, data)
    saver = User(email=f"{uuid4()}@example.com", hashed_password="x", full_name="Saver")
    db.add(saver)
    await db.flush()
    db.add(OrganizationMember(organization_id=data.org.id, user_id=saver.id, role="member"))
    group = Group(organization_id=data.org.id, name="Ops")
    db.add(group)
    await db.flush()
    db.add_all(
        [
            GroupMember(group_id=group.id, user_id=data.users[1].id, is_lead=True),
            GroupMember(group_id=group.id, user_id=saver.id, is_lead=False),
        ]
    )
    await db.flush()
    saver_ctx = AuthContext(user_id=saver.id, organization_id=data.org.id, role="member")
    board = await TaskService(db).open_board(
        saver_ctx, BoardEnsure(scope="group", scope_id=group.id)
    )
    table = await VirtualTableService(db).describe_table(lead, board.table_id)
    assert table.default_view_id is not None
    views = TableViewService(db)

    seen = await views.get_view(lead, board.table_id, table.default_view_id)
    assert (seen.owner_user_id, seen.can_manage, seen.can_delete) == (saver.id, True, True)
    renamed = await views.update_view(
        lead, board.table_id, table.default_view_id, TableViewUpdate(name="Ops board")
    )
    assert (renamed.name, renamed.can_manage) == ("Ops board", True)
    with pytest.raises(AuthorizationError):
        await views.update_view(
            saver_ctx, board.table_id, table.default_view_id, TableViewUpdate(name="Mine")
        )
    await views.delete_view(lead, board.table_id, table.default_view_id)


async def test_a_group_lead_is_told_the_board_default_view_uses_a_column_they_archive(
    db: AsyncSession,
) -> None:
    from app.schemas.table_view import TableViewConfig, TableViewUpdate
    from app.schemas.virtual_table import RecordSort
    from app.services.virtual_tables import TableViewService
    from app.services.virtual_tables.exceptions import SchemaDependencyError

    data = await world(db)
    lead = await _as_member(db, data)
    saver = User(email=f"{uuid4()}@example.com", hashed_password="x", full_name="Saver")
    db.add(saver)
    await db.flush()
    db.add(OrganizationMember(organization_id=data.org.id, user_id=saver.id, role="member"))
    group = Group(organization_id=data.org.id, name="Ops")
    db.add(group)
    await db.flush()
    db.add_all(
        [
            GroupMember(group_id=group.id, user_id=data.users[1].id, is_lead=True),
            GroupMember(group_id=group.id, user_id=saver.id, is_lead=False),
        ]
    )
    await db.flush()
    saver_ctx = AuthContext(user_id=saver.id, organization_id=data.org.id, role="member")
    board = await TaskService(db).open_board(
        saver_ctx, BoardEnsure(scope="group", scope_id=group.id)
    )
    tables = VirtualTableService(db)
    table = await tables.describe_table(lead, board.table_id)
    current = [ColumnInput.model_validate(column.model_dump()) for column in table.columns]
    table = await tables.update_schema(
        lead,
        board.table_id,
        SchemaUpdate(
            expected_version=table.schema_version,
            columns=[*current, ColumnInput(label="Priority", type="text")],
        ),
    )
    priority = next(column for column in table.columns if column.label == "Priority")
    assert table.default_view_id is not None
    await TableViewService(db).update_view(
        lead,
        board.table_id,
        table.default_view_id,
        TableViewUpdate(
            config=TableViewConfig(
                group_by=table.columns[1].id, sort=RecordSort(by=str(priority.id))
            )
        ),
    )

    with pytest.raises(SchemaDependencyError):
        await tables.update_schema(
            lead,
            board.table_id,
            SchemaUpdate(
                expected_version=table.schema_version,
                columns=[
                    ColumnInput.model_validate(
                        {**column.model_dump(), "archived": column.id == priority.id}
                    )
                    for column in table.columns
                ],
            ),
        )


async def test_a_member_who_sees_a_board_default_view_is_refused_it_not_told_it_is_missing(
    db: AsyncSession,
) -> None:
    from app.schemas.table_view import TableViewUpdate
    from app.services.virtual_tables import TableViewService

    data = await world(db)
    saver = await _as_member(db, data)
    other = User(email=f"{uuid4()}@example.com", hashed_password="x", full_name="Other")
    db.add(other)
    await db.flush()
    db.add(OrganizationMember(organization_id=data.org.id, user_id=other.id, role="member"))
    await db.flush()
    other_ctx = AuthContext(user_id=other.id, organization_id=data.org.id, role="member")
    board = await TaskService(db).open_board(saver, BoardEnsure(scope="organization"))
    table = await VirtualTableService(db).describe_table(other_ctx, board.table_id)
    assert table.default_view_id is not None
    views = TableViewService(db)

    with pytest.raises(AuthorizationError):
        await views.update_view(
            other_ctx, board.table_id, table.default_view_id, TableViewUpdate(name="Mine")
        )
    with pytest.raises(AuthorizationError):
        await views.delete_view(other_ctx, board.table_id, table.default_view_id)


@pytest.mark.parametrize("settled_before_archive", [False, True])
async def test_a_case_settled_while_its_board_is_archived_moves_the_task_once_it_returns(
    db: AsyncSession,
    settled_before_archive: bool,
) -> None:
    from app.db.models.virtual_table import VirtualTableRecord
    from app.services.outcome import OutcomeService

    data = await world(db)
    service = TaskService(db)
    owner = data.contexts[0]
    settled, still_open = [
        await service.create(
            owner, TaskCreate(title=title, start_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        for title in ("Send the approved draft", "Call the supplier")
    ]
    for task in (settled, still_open):
        await TaskExecution(db).wake(
            WakeTask(organization_id=data.org.id, task_id=task.id, revision=task.revision)
        )
    case = (await service.get(owner, settled.id)).outcome_id
    tables = VirtualTableService(db)
    await tables.archive_table(owner, settled.table_id)
    record = await db.get(VirtualTableRecord, settled.id)
    assert record is not None
    revision = record.revision

    await OutcomeService(db).settle(owner, case, "resolve", via="inbox")
    if settled_before_archive:
        # Settlement is stamped before taking the board lock; archive can win that lock.
        from app.db.models.outcome import Outcome
        from app.db.models.virtual_table import VirtualTable

        board_row = await db.get(VirtualTable, settled.table_id)
        case_row = await db.get(Outcome, case)
        assert board_row is not None and board_row.archived_at is not None
        assert case_row is not None
        case_row.settled_at = board_row.archived_at - timedelta(microseconds=1)
        await db.flush()

    await db.refresh(record)
    assert record.revision == revision

    await tables.unarchive_table(owner, settled.table_id)

    assert (await service.get(owner, settled.id)).status == "done"
    assert (await service.get(owner, still_open.id)).status == "waiting_for_user"


async def test_reopening_a_case_whose_task_board_is_archived_is_refused(db: AsyncSession) -> None:
    from app.db.models.suggestion import Suggestion
    from app.services.outcome import OutcomeService
    from app.services.suggestions import SuggestionService
    from app.services.virtual_tables.exceptions import TableArchivedError

    data = await world(db)
    service = TaskService(db)
    owner = data.contexts[0]
    task = await service.create(
        owner,
        TaskCreate(title="Check the draft", start_at=datetime.now(UTC) - timedelta(minutes=1)),
    )
    await TaskExecution(db).wake(
        WakeTask(organization_id=data.org.id, task_id=task.id, revision=task.revision)
    )
    task = await service.get(owner, task.id)
    await OutcomeService(db).settle(owner, task.outcome_id, "mute", via="inbox")
    finding = await db.scalar(select(Suggestion).where(Suggestion.outcome_id == task.outcome_id))
    assert finding is not None
    await VirtualTableService(db).archive_table(owner, task.table_id)

    with pytest.raises(TableArchivedError):
        await SuggestionService(db).restore(owner, finding.id)


async def test_waking_a_task_waits_for_its_board_before_it_holds_the_task(engine) -> None:
    """Restoring a board holds its table, then locks each task: a wake that held its task
    first and then waited on the table would deadlock with it."""
    import asyncio

    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models.virtual_table import VirtualTable, VirtualTableRecord

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        data = await world(db)
        task = await TaskService(db).create(
            data.contexts[0],
            TaskCreate(title="Send the draft", start_at=datetime.now(UTC) - timedelta(minutes=1)),
        )
        await db.commit()

    async def wake() -> None:
        async with factory() as db:
            await TaskExecution(db).wake(
                WakeTask(organization_id=data.org.id, task_id=task.id, revision=task.revision)
            )
            await db.commit()

    async with factory() as restoring:
        await restoring.execute(
            select(VirtualTable.id).where(VirtualTable.id == task.table_id).with_for_update()
        )
        waking = asyncio.create_task(wake())
        await asyncio.sleep(0.5)
        try:
            held = await restoring.scalar(
                select(VirtualTableRecord.id)
                .where(VirtualTableRecord.id == task.id)
                .with_for_update(nowait=True)
            )
        except DBAPIError:
            held = None
        await restoring.rollback()
    await waking

    assert held == task.id
    async with factory() as db:
        assert (await TaskService(db).get(data.contexts[0], task.id)).status == "waiting_for_user"
