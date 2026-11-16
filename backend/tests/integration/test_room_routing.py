"""Room planning is inert until human review; accepted work keeps canonical authority."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.background import discard_deferred
from app.core.exceptions import AlreadyExistsError, AuthorizationError, NotFoundError
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.background_job import BackgroundJob
from app.db.models.organization import OrganizationMember
from app.db.models.project import Project
from app.db.models.room_routing import RoomLeadPolicy, RoomRoutingProposal, RoomTaskLink
from app.db.models.task_board import TaskBoard, TaskLink
from app.db.models.user import User
from app.repositories import agent_run as run_repo
from app.repositories import room_routing as routing_repo
from app.repositories import room_submission as room_repo
from app.schemas.room_routing import (
    RoomLeadPolicyWrite,
    RoomProposalAccept,
    RoomProposalCreate,
    RoomProposalDiscard,
    RoomProposalItem,
)
from app.schemas.room_submission import RoomMessageCreate
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.room_routing import RoomRoutingService
from app.services.room_submission import RoomSubmissionService
from app.services.task_access import execution_allows
from app.services.tasks import TaskService
from app.worker.jobs import FIRE_TRIGGER
from tests.integration.test_room_submissions import seed

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
async def room(db):
    value = await seed(db)
    value.user.full_name = "Room requester"
    await db.flush()
    yield value
    discard_deferred(db)


async def planning(db, room, *, thread_root_message_id=None, **changes):
    service = RoomRoutingService(db)
    policy = await service.policy(room.ctx, room.conversation.id)
    if policy.revision == 0:
        policy = await service.update_policy(
            room.ctx,
            room.conversation.id,
            RoomLeadPolicyWrite(
                expected_revision=0,
                enabled=True,
                lead_agent_id=room.agent.id,
                specialist_agent_ids=[room.agent.id],
            ),
        )
    posted = await RoomSubmissionService(db).post(
        room.ctx,
        room.conversation.id,
        RoomMessageCreate(
            client_message_id=f"lead-{uuid4()}",
            content="Please prepare a reviewable handoff",
            intent="ask_lead",
            expected_policy_revision=policy.revision,
            thread_root_message_id=thread_root_message_id,
        ),
        room.user,
    )
    submission = await room_repo.get(
        db, posted.request.id, organization_id=room.ctx.organization_id
    )
    run = await run_repo.create_run(
        db,
        organization_id=room.ctx.organization_id,
        agent_id=room.agent.id,
        agent_version_id=room.version.id,
        user_id=room.user.id,
        conversation_id=room.conversation.id,
        surface="web",
        model_label="test",
        provider="test",
        started_at=datetime.now(UTC),
    )
    submission.status, submission.run_id = "running", run.id
    await db.flush()
    item = RoomProposalItem.model_validate(
        {
            "title": "Prepare a draft",
            "expected_result": "A draft for the requester to review",
            "agent_id": room.agent.id,
            "agent_version_id": room.version.id,
            **changes,
        }
    )
    proposal = await service.propose(
        room.ctx.organization_id, submission.id, run.id, RoomProposalCreate(items=[item])
    )
    submission.status, run.status = "completed", "completed"
    await db.flush()
    proposal = await service.read(room.ctx, room.conversation.id, proposal.id)
    return service, submission, proposal


def acceptance(proposal, **changes):
    return RoomProposalAccept.model_validate(
        {
            "expected_revision": proposal.revision,
            "idempotency_key": f"accept-{proposal.id}",
            "selected_item_ids": [item.proposal_item_id for item in proposal.items],
            **changes,
        }
    )


async def fires(db):
    return await db.scalar(
        select(func.count())
        .select_from(BackgroundJob)
        .where(BackgroundJob.kind == FIRE_TRIGGER.kind)
    )


async def test_explicit_acceptance_dispatches_once_and_cards_never_expose_working_chat_ids(
    db, room
):
    service, submission, proposal = await planning(db, room)
    assert proposal.can_accept and proposal.can_discard
    assert proposal.items[0].accountable_user_name == "Room requester"
    assert await db.scalar(select(func.count()).select_from(TaskBoard)) == 0
    assert await fires(db) == 0
    decision = acceptance(proposal)
    accepted = await service.accept(room.ctx, room.conversation.id, proposal.id, decision)
    again = await service.accept(room.ctx, room.conversation.id, proposal.id, decision)
    assert accepted == again and accepted.decision == "accepted" and accepted.revision == 2
    assert not accepted.can_accept and not accepted.can_discard
    assert await fires(db) == 1
    assert await db.scalar(select(func.count()).select_from(TaskLink)) == 1
    cards = await service.task_cards(
        room.ctx, room.conversation.id, thread_root_message_id=None, limit=50
    )
    assert len(cards.items) == 1 and not cards.has_more
    card = cards.items[0]
    task = await TaskService(db).get(room.ctx, card.task_id)
    canonical = await db.get(TaskLink, task.id)
    assert canonical.trigger_id is not None and canonical.conversation_id is not None
    assert canonical.conversation_id != room.conversation.id
    assert (await db.get(AgentTrigger, canonical.trigger_id)).pinned_version_id == room.version.id
    assert card.title == task.title and card.revision == task.revision
    assert card.accountable_user_name == "Room requester"
    serialized = card.model_dump_json()
    assert "conversation_id" not in serialized and "outcome_id" not in serialized
    assert str(canonical.conversation_id) not in serialized
    assert str(canonical.outcome_id) not in serialized if canonical.outcome_id else True
    with pytest.raises(AlreadyExistsError):
        await service.accept(
            room.ctx,
            room.conversation.id,
            proposal.id,
            acceptance(proposal, selected_item_ids=[uuid4()]),
        )
    assert await fires(db) == 1
    assert "RoomLeadPolicy" in repr(
        await routing_repo.policy(db, room.ctx.organization_id, room.conversation.id)
    )
    assert "RoomRoutingProposal" in repr(
        await routing_repo.proposal(
            db,
            proposal.id,
            organization_id=room.ctx.organization_id,
            conversation_id=room.conversation.id,
        )
    )
    assert "RoomTaskLink" in repr(await db.scalar(select(RoomTaskLink)))


async def test_source_room_deletion_preserves_review_provenance_and_canonical_task_authority(
    db, room
):
    service, _, proposal = await planning(db, room)
    await service.accept(room.ctx, room.conversation.id, proposal.id, acceptance(proposal))
    link = await db.scalar(select(RoomTaskLink))
    task_id, provenance = link.task_id, dict(link.provenance)
    canonical = await db.get(TaskLink, task_id)
    trigger_id, working_id = canonical.trigger_id, canonical.conversation_id
    assert await execution_allows(db, room.ctx, trigger_id)
    await db.delete(room.conversation)
    await db.flush()
    await db.refresh(link)
    assert link.proposal_id is None and link.provenance == provenance
    assert set(provenance) == {
        "kind",
        "proposal_id",
        "proposal_item_id",
        "policy_revision",
        "specialist_agent_id",
        "specialist_version_id",
        "requester_id",
        "accepted_revision",
    }
    assert str(working_id) not in str(provenance)
    assert (await TaskService(db).get(room.ctx, task_id)).id == task_id
    assert (await db.get(TaskLink, task_id)).trigger_id == trigger_id
    assert await execution_allows(db, room.ctx, trigger_id)
    assert not await execution_allows(db, replace(room.ctx, organization_id=uuid4()), trigger_id)
    assert await fires(db) == 1


async def test_another_accountable_member_must_start_their_own_agent_work(db, room):
    other = User(
        id=uuid4(),
        email=f"{uuid4()}@example.com",
        full_name="Reviewed teammate",
        hashed_password="x",
        is_active=True,
    )
    db.add(other)
    await db.flush()
    db.add(
        OrganizationMember(
            organization_id=room.ctx.organization_id, user_id=other.id, role="member"
        )
    )
    (await db.get(Project, room.conversation.project_id)).visibility = "org"
    room.agent.visibility = "org"
    await db.flush()
    service, _, proposal = await planning(db, room, accountable_user_id=other.id)
    assert proposal.items[0].accountable_user_name == "Reviewed teammate"
    await service.accept(room.ctx, room.conversation.id, proposal.id, acceptance(proposal))
    cards = await service.task_cards(
        room.ctx, room.conversation.id, thread_root_message_id=None, limit=50
    )
    task = await TaskService(db).get(room.ctx, cards.items[0].task_id)
    assert (
        task.assignee_user_id == other.id and task.next_actor == "user" and task.status == "planned"
    )
    assert await fires(db) == 0
    assert (await db.get(TaskLink, task.id)).trigger_id is None


async def test_existing_tasks_are_linked_at_the_reviewed_revision_without_rewriting_or_dispatch(
    db, room
):
    tasks = TaskService(db)
    task = await tasks.create(
        room.ctx,
        TaskCreate(
            scope="project",
            scope_id=room.conversation.project_id,
            title="Existing commitment",
            description="Keep this agreed description",
            assignee_agent_id=room.agent.id,
            assignee_user_id=room.ctx.user_id,
            next_actor="user",
        ),
    )
    service, _, proposal = await planning(
        db, room, existing_task_id=task.id, expected_task_revision=task.revision
    )
    await service.accept(room.ctx, room.conversation.id, proposal.id, acceptance(proposal))
    assert await tasks.get(room.ctx, task.id) == task
    assert await fires(db) == 0
    assert (await db.scalar(select(RoomTaskLink))).accepted_revision == task.revision


async def test_changed_task_revision_refuses_acceptance_and_keeps_the_proposal_pending(db, room):
    tasks = TaskService(db)
    task = await tasks.create(
        room.ctx,
        TaskCreate(
            scope="project",
            scope_id=room.conversation.project_id,
            title="Existing commitment",
            assignee_agent_id=room.agent.id,
            assignee_user_id=room.ctx.user_id,
            next_actor="user",
        ),
    )
    service, _, proposal = await planning(
        db, room, existing_task_id=task.id, expected_task_revision=task.revision
    )
    await tasks.update(
        room.ctx, task.id, TaskUpdate(expected_revision=task.revision, title="Revised by a human")
    )
    with pytest.raises(AlreadyExistsError, match="existing task changed"):
        await service.accept(room.ctx, room.conversation.id, proposal.id, acceptance(proposal))
    assert (await service.read(room.ctx, room.conversation.id, proposal.id)).decision == "pending"
    assert await db.scalar(select(func.count()).select_from(RoomTaskLink)) == 0
    assert await fires(db) == 0


@pytest.mark.parametrize(
    "change", ["policy", "unfinished", "foreign_tenant", "api_key", "revision"]
)
async def test_acceptance_rechecks_live_authority_and_review_context(db, room, change):
    service, submission, proposal = await planning(db, room)
    ctx, decision = room.ctx, acceptance(proposal)
    if change == "policy":
        await service.update_policy(
            ctx, room.conversation.id, RoomLeadPolicyWrite(expected_revision=1, enabled=False)
        )
    elif change == "unfinished":
        submission.status = "running"
        await db.flush()
    elif change == "foreign_tenant":
        ctx = replace(ctx, organization_id=uuid4())
    elif change == "api_key":
        ctx = replace(ctx, api_key_id=uuid4())
    else:
        decision = acceptance(proposal, expected_revision=proposal.revision + 1)
    with pytest.raises((AlreadyExistsError, AuthorizationError, NotFoundError)):
        await service.accept(ctx, room.conversation.id, proposal.id, decision)
    assert await db.scalar(select(func.count()).select_from(RoomTaskLink)) == 0
    assert await fires(db) == 0


async def test_a_raced_specialist_pin_rolls_back_the_task_and_queued_fire(db, room, monkeypatch):
    service, _, proposal = await planning(db, room)
    monkeypatch.setattr(routing_repo, "dispatch_version", AsyncMock(return_value=uuid4()))
    with pytest.raises(AlreadyExistsError, match="specialist version changed"):
        async with db.begin_nested():
            await service.accept(room.ctx, room.conversation.id, proposal.id, acceptance(proposal))
    assert await db.scalar(select(func.count()).select_from(TaskBoard)) == 0
    assert await db.scalar(select(func.count()).select_from(RoomTaskLink)) == 0
    assert await fires(db) == 0


async def test_discard_is_final_idempotent_and_never_starts_work(db, room):
    service, _, proposal = await planning(db, room)
    decision = RoomProposalDiscard(expected_revision=proposal.revision, idempotency_key="decline")
    first = await service.discard(room.ctx, room.conversation.id, proposal.id, decision)
    again = await service.discard(room.ctx, room.conversation.id, proposal.id, decision)
    assert first == again and first.decision == "discarded" and first.revision == 2
    with pytest.raises(AlreadyExistsError):
        await service.accept(room.ctx, room.conversation.id, proposal.id, acceptance(proposal))
    assert await db.scalar(select(func.count()).select_from(RoomTaskLink)) == 0
    assert await fires(db) == 0


async def test_policy_and_proposal_lists_are_scoped_and_paginated(db, room):
    service = RoomRoutingService(db)
    initial = await service.policy(room.ctx, room.conversation.id)
    assert initial.revision == 0 and initial.can_edit and not initial.can_ask
    service, _, proposal = await planning(db, room)
    first = await service.list(room.ctx, room.conversation.id, thread_root_message_id=None, limit=1)
    later = await service.list(
        room.ctx, room.conversation.id, thread_root_message_id=None, limit=1, skip=1
    )
    assert [value.id for value in first.items] == [proposal.id] and not first.has_more
    assert later.items == []
    with pytest.raises(NotFoundError):
        await service.list(room.ctx, room.conversation.id, thread_root_message_id=uuid4(), limit=1)
    with pytest.raises(NotFoundError):
        await service.read(room.ctx, room.conversation.id, uuid4())


async def test_ask_lead_retries_keep_the_original_intent_after_a_policy_change(db, room):
    service = RoomRoutingService(db)
    await service.update_policy(
        room.ctx,
        room.conversation.id,
        RoomLeadPolicyWrite(
            expected_revision=0,
            enabled=True,
            lead_agent_id=room.agent.id,
            specialist_agent_ids=[room.agent.id],
        ),
    )
    request = RoomMessageCreate(
        client_message_id="stable-lead",
        content="Review the plan",
        intent="ask_lead",
        expected_policy_revision=1,
    )
    rooms = RoomSubmissionService(db)
    first = await rooms.post(room.ctx, room.conversation.id, request, room.user)
    await service.update_policy(
        room.ctx, room.conversation.id, RoomLeadPolicyWrite(expected_revision=1, enabled=False)
    )
    assert await rooms.post(room.ctx, room.conversation.id, request, room.user) == first
    with pytest.raises(AlreadyExistsError) as refused:
        await rooms.post(
            room.ctx,
            room.conversation.id,
            request.model_copy(update={"client_message_id": "new-stale-lead"}),
            room.user,
        )
    assert refused.value.code == "ROOM_LEAD_POLICY_CHANGED"
    assert (
        await room_repo.for_client(
            db,
            organization_id=room.ctx.organization_id,
            conversation_id=room.conversation.id,
            requester_id=room.ctx.user_id,
            client_message_id="new-stale-lead",
        )
        is None
    )
    with pytest.raises(AlreadyExistsError):
        await rooms.post(
            room.ctx,
            room.conversation.id,
            request.model_copy(update={"intent": "message", "expected_policy_revision": None}),
            room.user,
        )
    with pytest.raises(AlreadyExistsError):
        await rooms.authority(
            await room_repo.get(db, first.request.id, organization_id=room.ctx.organization_id)
        )
    assert await fires(db) == 0


async def test_subthread_cards_keep_their_source_and_the_room_list_includes_all_threads(db, room):
    rooms = RoomSubmissionService(db)
    root = await rooms.post(
        room.ctx,
        room.conversation.id,
        RoomMessageCreate(client_message_id="topic-root", content="Discuss this topic"),
        room.user,
    )
    service, _, main = await planning(db, room)
    service, _, thread = await planning(db, room, thread_root_message_id=root.message.id)
    await service.accept(room.ctx, room.conversation.id, main.id, acceptance(main))
    await service.accept(room.ctx, room.conversation.id, thread.id, acceptance(thread))
    first = await service.list(room.ctx, room.conversation.id, thread_root_message_id=None, limit=1)
    second = await service.list(
        room.ctx, room.conversation.id, thread_root_message_id=None, limit=1, skip=1
    )
    assert first.has_more and not second.has_more
    assert {first.items[0].id, second.items[0].id} == {main.id, thread.id}
    scoped = await service.list(
        room.ctx, room.conversation.id, thread_root_message_id=root.message.id, limit=10
    )
    assert [proposal.id for proposal in scoped.items] == [thread.id]
    all_cards = await service.task_cards(
        room.ctx, room.conversation.id, thread_root_message_id=None, limit=1
    )
    later_cards = await service.task_cards(
        room.ctx, room.conversation.id, thread_root_message_id=None, limit=1, skip=1
    )
    assert all_cards.has_more and not later_cards.has_more
    assert {all_cards.items[0].proposal_id, later_cards.items[0].proposal_id} == {
        main.id,
        thread.id,
    }
    cards = await service.task_cards(
        room.ctx, room.conversation.id, thread_root_message_id=root.message.id, limit=10
    )
    assert len(cards.items) == 1 and cards.items[0].proposal_id == thread.id
    assert cards.items[0].thread_root_message_id == root.message.id
    assert cards.items[0].message_id == thread.message_id
    with pytest.raises(NotFoundError):
        await service.task_cards(
            room.ctx, room.conversation.id, thread_root_message_id=thread.message_id, limit=10
        )
    foreign = await seed(db)
    foreign_root = await rooms.post(
        foreign.ctx,
        foreign.conversation.id,
        RoomMessageCreate(client_message_id="foreign-root", content="Private topic"),
        foreign.user,
    )
    with pytest.raises(NotFoundError):
        await service.list(
            room.ctx, room.conversation.id, thread_root_message_id=foreign_root.message.id, limit=10
        )
    assert await fires(db) == 2


@pytest.mark.parametrize("target", ["policy", "proposal", "task"])
async def test_database_constraints_refuse_cross_organization_handoff_links(db, room, target):
    service, _, proposal = await planning(db, room)
    await service.accept(room.ctx, room.conversation.id, proposal.id, acceptance(proposal))
    if target == "policy":
        statement = update(RoomLeadPolicy).where(
            RoomLeadPolicy.conversation_id == room.conversation.id
        )
    elif target == "proposal":
        statement = update(RoomRoutingProposal).where(RoomRoutingProposal.id == proposal.id)
    else:
        statement = update(RoomTaskLink).where(RoomTaskLink.proposal_id == proposal.id)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(statement.values(organization_id=uuid4()))
    assert await fires(db) == 1
