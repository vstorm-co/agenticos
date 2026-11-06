"""Task boards exercise real table revisions, live audiences and durable wakeups."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.group import Group, GroupMember
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.task_board import TaskBoard, TaskLink
from app.db.models.user import User
from app.schemas.task import BoardEnsure, TaskCreate, TaskUpdate
from app.schemas.virtual_table import ColumnInput, RecordUpdate, SchemaUpdate
from app.services.task_execution import TaskExecution
from app.services.tasks import TaskService
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
async def test_agent_task_is_a_single_pinned_execution_and_ends_waiting_for_review(
    db: AsyncSession,
    delay: int,
    scope: str,
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
    run.status = "completed"
    await db.flush()
    await TaskExecution(db).finished(trigger, run)
    current = await service.get(data.contexts[0], task.id)
    assert current.status == "waiting_for_user" and current.outcome_id is not None
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
