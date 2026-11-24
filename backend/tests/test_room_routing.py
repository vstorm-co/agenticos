"""Refusals and live redaction around the real canonical-task handoff boundary.

PostgreSQL integration tests prove durable effects and constraints. These cases
drive the authority changes and read/lock races that must refuse before effects.
"""

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.spec import AgentSpec
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.db.models.conversation import Conversation, Message
from app.db.models.room_routing import RoomLeadPolicy, RoomRoutingProposal
from app.db.models.room_submission import RoomSubmission
from app.schemas.room_routing import (
    RoomLeadPolicyWrite,
    RoomProposalAccept,
    RoomProposalCreate,
    RoomProposalDiscard,
    RoomProposalItem,
)
from app.services import room_routing as module

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def routing(monkeypatch):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")
    room = Conversation(
        id=uuid4(), organization_id=ctx.organization_id, project_id=uuid4(), is_archived=False
    )
    message = Message(id=uuid4(), conversation_id=room.id, thread_root_message_id=None)
    agent, version, run_id = uuid4(), uuid4(), uuid4()
    policy = RoomLeadPolicy(
        organization_id=ctx.organization_id,
        conversation_id=room.id,
        enabled=True,
        revision=1,
        lead_agent_id=agent,
        lead_version_id=version,
        specialists=[{"agent_id": str(agent), "version_id": str(version)}],
        max_items=3,
    )
    submission = RoomSubmission(
        id=uuid4(),
        organization_id=ctx.organization_id,
        conversation_id=room.id,
        requester_id=ctx.user_id,
        message_id=message.id,
        intent="ask_lead",
        lead_policy_revision=1,
        agent_id=agent,
        version_id=version,
        run_id=run_id,
        status="completed",
    )
    item = RoomProposalItem(
        title="Reviewable work",
        expected_result="An explicit result for the human to review",
        agent_id=agent,
        agent_version_id=version,
        accountable_user_id=ctx.user_id,
    )
    proposal = RoomRoutingProposal(
        id=uuid4(),
        organization_id=ctx.organization_id,
        conversation_id=room.id,
        submission_id=submission.id,
        message_id=message.id,
        thread_root_message_id=None,
        requester_id=ctx.user_id,
        lead_run_id=run_id,
        policy_revision=1,
        revision=1,
        items=[{**item.model_dump(mode="json"), "proposal_item_id": str(uuid4())}],
        decision="pending",
        accepted_item_ids=[],
        created_at=datetime.now(UTC),
    )
    db = MagicMock(info={})
    service = module.RoomRoutingService(db)
    service.rooms.room = AsyncMock(return_value=room)
    service.rooms.authority = AsyncMock(return_value=(ctx, room, message))
    agent_row = SimpleNamespace(id=agent, name="Published specialist")
    spec = AgentSpec(name=agent_row.name)
    service.registry.get_runnable_spec = AsyncMock(return_value=(agent_row, spec, version))
    service.registry.get_pinned_spec = AsyncMock(return_value=(agent_row, spec, version))
    task = SimpleNamespace(
        id=uuid4(),
        table_id=uuid4(),
        scope="project",
        scope_id=room.project_id,
        revision=1,
        assignee_agent_id=agent,
        assignee_user_id=ctx.user_id,
        title="Canonical title",
        description="Current canonical description",
        status="planned",
        next_actor="user",
        due_at=None,
    )
    service.tasks.get = AsyncMock(return_value=task)
    service.tasks.create = AsyncMock(return_value=task)
    monkeypatch.setattr(module, "hold_subject", AsyncMock())
    monkeypatch.setattr(module, "announce_request", MagicMock())
    monkeypatch.setattr(module, "acting_member", AsyncMock(return_value=ctx))
    monkeypatch.setattr(module, "scope_allows", AsyncMock(return_value=True))
    monkeypatch.setattr(module, "resolve_access", AsyncMock(return_value=True))
    monkeypatch.setattr(module.project_repo, "get", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(
        module.user_repo,
        "get_by_id",
        AsyncMock(return_value=SimpleNamespace(full_name="Member name")),
    )
    monkeypatch.setattr(module.routing_repo, "policy", AsyncMock(return_value=policy))
    monkeypatch.setattr(module.routing_repo, "proposal", AsyncMock(return_value=proposal))
    monkeypatch.setattr(module.routing_repo, "for_submission", AsyncMock(return_value=None))
    monkeypatch.setattr(module.room_repo, "get", AsyncMock(return_value=submission))

    async def save(_db, row):
        if row.created_at is None:
            row.created_at = datetime.now(UTC)
        return row

    monkeypatch.setattr(module.routing_repo, "save", AsyncMock(side_effect=save))
    monkeypatch.setattr(
        module.virtual_table_repo,
        "get_table",
        AsyncMock(return_value=SimpleNamespace(archived_at=None)),
    )
    monkeypatch.setattr(module.task_repo, "record", AsyncMock(return_value=SimpleNamespace()))
    return SimpleNamespace(
        ctx=ctx,
        room=room,
        message=message,
        policy=policy,
        submission=submission,
        item=item,
        proposal=proposal,
        service=service,
        task=task,
        db=db,
        agent_row=agent_row,
        spec=spec,
        version=version,
    )


def decision(routing, **changes):
    return RoomProposalAccept.model_validate(
        {
            "expected_revision": 1,
            "idempotency_key": "review-token",
            "selected_item_ids": [routing.proposal.items[0]["proposal_item_id"]],
            **changes,
        }
    )


async def accept(routing, **changes):
    return await routing.service.accept(
        routing.ctx, routing.room.id, routing.proposal.id, decision(routing, **changes)
    )


def existing_item(routing):
    routing.proposal.items[0].update(
        existing_task_id=str(routing.task.id), expected_task_revision=routing.task.revision
    )


@pytest.mark.parametrize("missing", ["user_id", "project_id", "member", "grant", "person"])
async def test_accountable_names_require_a_current_eligible_member_and_never_fall_back_to_email(
    routing, missing
):
    user_id, project_id = routing.ctx.user_id, routing.room.project_id
    if missing == "user_id":
        user_id = None
    elif missing == "project_id":
        project_id = None
    elif missing == "member":
        module.acting_member.return_value = None
    elif missing == "grant":
        module.scope_allows.return_value = False
    else:
        module.user_repo.get_by_id.return_value = None
    assert await routing.service._accountable_name(routing.ctx, user_id, project_id) is None
    assert await routing.service._accountable_name(routing.ctx, user_id, project_id) is None
    assert module.user_repo.get_by_id.await_count <= 1


async def test_unrunnable_agents_are_redacted_from_policy_and_proposals(routing):
    routing.service.registry.get_runnable_spec.side_effect = AuthorizationError()
    policy = await routing.service.policy(routing.ctx, routing.room.id)
    proposal = await routing.service.read(routing.ctx, routing.room.id, routing.proposal.id)
    assert policy.lead is None and policy.specialists == [] and not policy.can_ask
    assert proposal.items[0].agent is None
    routing.service.registry.get_runnable_spec.assert_awaited_once()


async def test_room_write_revocation_hides_decision_capabilities_at_the_same_revision(routing):
    async def room(_ctx, _id, *, for_write=False):
        if for_write:
            raise AuthorizationError()
        return routing.room

    routing.service.rooms.room.side_effect = room
    policy = await routing.service.policy(routing.ctx, routing.room.id)
    proposal = await routing.service.read(routing.ctx, routing.room.id, routing.proposal.id)
    assert policy.lead is not None and not policy.can_ask
    assert proposal.revision == 1 and not proposal.can_accept and not proposal.can_discard
    module.routing_repo.save.assert_not_awaited()


@pytest.mark.parametrize("reason", ["no_project", "archived", "project_missing", "no_edit"])
async def test_policy_changes_require_the_current_editable_project(routing, reason):
    if reason == "no_project":
        routing.room.project_id = None
    elif reason == "archived":
        routing.room.is_archived = True
    elif reason == "project_missing":
        module.project_repo.get.return_value = None
    else:
        module.resolve_access.return_value = False
    policy = await routing.service.policy(routing.ctx, routing.room.id)
    assert not policy.can_edit
    with pytest.raises(AuthorizationError):
        await routing.service.update_policy(
            routing.ctx, routing.room.id, RoomLeadPolicyWrite(expected_revision=1, enabled=False)
        )
    module.routing_repo.save.assert_not_awaited()


async def test_policy_compare_and_swap_refuses_a_stale_editor_before_resolving_new_agents(routing):
    with pytest.raises(AlreadyExistsError):
        await routing.service.update_policy(
            routing.ctx, routing.room.id, RoomLeadPolicyWrite(expected_revision=0, enabled=False)
        )
    routing.service.registry.get_runnable_spec.assert_not_awaited()
    module.routing_repo.save.assert_not_awaited()


@pytest.mark.parametrize("reason", ["ordinary", "unversioned", "different_lead"])
async def test_only_the_original_explicit_pinned_request_can_become_a_planner(routing, reason):
    if reason == "ordinary":
        routing.submission.intent = "message"
    elif reason == "unversioned":
        routing.submission.lead_policy_revision = None
    else:
        routing.submission.agent_id = uuid4()
    with pytest.raises((BadRequestError, AlreadyExistsError)):
        await routing.service.submission_policy(routing.ctx, routing.submission)
    routing.service.tasks.create.assert_not_awaited()


@pytest.mark.parametrize(
    "reason", ["different_project", "missing_table", "archived_table", "missing_record"]
)
async def test_existing_task_references_are_rechecked_under_the_task_lock(routing, reason):
    existing_item(routing)
    if reason == "different_project":
        routing.task.scope_id = uuid4()
    elif reason == "missing_table":
        module.virtual_table_repo.get_table.return_value = None
    elif reason == "archived_table":
        module.virtual_table_repo.get_table.return_value.archived_at = datetime.now(UTC)
    else:
        module.task_repo.record.return_value = None
    with pytest.raises(NotFoundError):
        await accept(routing)
    routing.service.tasks.create.assert_not_awaited()
    module.routing_repo.save.assert_not_awaited()
    if reason != "different_project":
        assert module.virtual_table_repo.get_table.call_args.kwargs["for_share"]


@pytest.mark.parametrize(
    "reason",
    ["not_specialist", "new_version", "no_project", "no_task_edit", "no_owner", "owner_no_edit"],
)
async def test_acceptance_rejects_stale_specialists_and_ineligible_task_owners(routing, reason):
    if reason == "not_specialist":
        routing.policy.specialists = []
    elif reason == "new_version":
        routing.service.registry.get_runnable_spec.return_value = (
            routing.agent_row,
            routing.spec,
            uuid4(),
        )
    elif reason == "no_project":
        routing.room.project_id = None
    elif reason == "no_task_edit":
        module.scope_allows.return_value = False
    elif reason == "no_owner":
        module.acting_member.return_value = None
    else:
        module.scope_allows.side_effect = [True, False]
    with pytest.raises((BadRequestError, AlreadyExistsError, AuthorizationError)):
        await accept(routing)
    routing.service.tasks.create.assert_not_awaited()
    module.routing_repo.save.assert_not_awaited()


@pytest.mark.parametrize("visibility", ["current", "unrunnable", "old_version", "empty"])
async def test_planner_exposes_only_current_runnable_specialists_and_writes_in_a_fresh_context(
    routing, monkeypatch, visibility
):
    if visibility == "unrunnable":
        routing.service.registry.get_runnable_spec.side_effect = AuthorizationError()
    elif visibility == "old_version":
        routing.service.registry.get_runnable_spec.return_value = (
            routing.agent_row,
            routing.spec,
            uuid4(),
        )
    elif visibility == "empty":
        routing.policy.specialists = []
    capability = await routing.service.planner(routing.submission)
    context = json.loads(capability.context)
    assert context["requester_id"] == str(routing.ctx.user_id)
    assert context["max_items"] == 3
    assert len(context["specialists"]) == (1 if visibility == "current" else 0)
    assert "conversation_id" not in context
    original = (routing.submission.organization_id, routing.submission.id)
    routing.submission.organization_id, routing.submission.id = uuid4(), uuid4()
    fresh = MagicMock()
    writer = AsyncMock(return_value=routing.proposal)

    @asynccontextmanager
    async def transaction():
        yield fresh

    monkeypatch.setattr("app.db.session.get_worker_db_context", transaction)
    factory = MagicMock(return_value=SimpleNamespace(propose=writer))
    monkeypatch.setattr(module, "RoomRoutingService", factory)
    request = RoomProposalCreate(items=[routing.item])
    assert await capability.create_proposal(routing.submission.run_id, request) is routing.proposal
    factory.assert_called_once_with(fresh)
    writer.assert_awaited_once_with(*original, routing.submission.run_id, request)


@pytest.mark.parametrize(
    "reason", ["missing", "wrong_run", "finished", "removed_under_lock", "settled_under_lock"]
)
async def test_proposal_writes_recheck_the_owned_live_run_after_taking_the_room_lock(
    routing, reason
):
    routing.submission.status = "running"
    run_id = routing.submission.run_id
    if reason == "missing":
        module.room_repo.get.return_value = None
    elif reason == "wrong_run":
        run_id = uuid4()
    elif reason == "finished":
        routing.submission.status = "completed"
    elif reason == "removed_under_lock":
        module.room_repo.get.side_effect = [routing.submission, None]
    else:
        settled = SimpleNamespace(run_id=run_id, status="completed")
        module.room_repo.get.side_effect = [routing.submission, settled]
    with pytest.raises(NotFoundError):
        await routing.service.propose(
            routing.ctx.organization_id,
            routing.submission.id,
            run_id,
            RoomProposalCreate(items=[routing.item]),
        )
    routing.service.rooms.authority.assert_not_awaited()
    module.routing_repo.save.assert_not_awaited()


async def test_room_specific_item_limit_is_enforced_before_work_or_proposal_writes(routing):
    routing.submission.status = "running"
    routing.policy.max_items = 1
    with pytest.raises(BadRequestError, match="at most 1"):
        await routing.service.propose(
            routing.ctx.organization_id,
            routing.submission.id,
            routing.submission.run_id,
            RoomProposalCreate(items=[routing.item, routing.item]),
        )
    module.routing_repo.save.assert_not_awaited()
    routing.service.tasks.create.assert_not_awaited()


async def test_repeating_one_model_proposal_keeps_its_ids_and_refuses_a_changed_body(routing):
    routing.submission.status = "running"
    data = RoomProposalCreate(items=[routing.item])
    args = (routing.ctx.organization_id, routing.submission.id, routing.submission.run_id)
    first = await routing.service.propose(*args, data)
    stored = module.routing_repo.save.call_args.args[1]
    module.routing_repo.for_submission.return_value = stored
    second = await routing.service.propose(*args, data)
    assert first.id == second.id and first.items == second.items
    with pytest.raises(AlreadyExistsError, match="different proposal"):
        await routing.service.propose(
            *args, RoomProposalCreate(items=[routing.item.model_copy(update={"title": "Changed"})])
        )
    module.routing_repo.save.assert_awaited_once()
    routing.service.tasks.create.assert_not_awaited()


async def test_existing_task_ids_are_redacted_when_the_reader_loses_board_access(routing):
    existing_item(routing)
    routing.service.tasks.get.side_effect = AuthorizationError()
    result = await routing.service.read(routing.ctx, routing.room.id, routing.proposal.id)
    assert result.items[0].existing_task_id is None
    assert result.items[0].expected_task_revision is None


@pytest.mark.parametrize(
    "reason",
    [
        "missing",
        "different_requester",
        "changed_requester",
        "changed_source",
        "changed_policy",
        "foreign_item",
    ],
)
async def test_decisions_are_bound_to_the_original_human_room_policy_and_selected_items(
    routing, reason
):
    changes = {}
    if reason == "missing":
        module.routing_repo.proposal.return_value = None
    elif reason == "different_requester":
        routing.proposal.requester_id = uuid4()
    elif reason == "changed_requester":
        routing.service.rooms.authority.return_value = (
            replace(routing.ctx, user_id=uuid4()),
            routing.room,
            routing.message,
        )
    elif reason == "changed_source":
        routing.service.rooms.authority.return_value = (
            routing.ctx,
            SimpleNamespace(id=uuid4()),
            routing.message,
        )
    elif reason == "changed_policy":
        routing.proposal.policy_revision = 2
    else:
        changes["selected_item_ids"] = [uuid4()]
    with pytest.raises((NotFoundError, AuthorizationError, AlreadyExistsError, BadRequestError)):
        await accept(routing, **changes)
    routing.service.tasks.create.assert_not_awaited()
    module.routing_repo.save.assert_not_awaited()


async def test_discard_can_finish_when_the_submission_was_removed_without_announcing_another_run(
    routing,
):
    module.room_repo.get.return_value = None
    result = await routing.service.discard(
        routing.ctx,
        routing.room.id,
        routing.proposal.id,
        RoomProposalDiscard(expected_revision=1, idempotency_key="discard-token"),
    )
    assert result.decision == "discarded"
    module.announce_request.assert_not_called()
    routing.service.tasks.create.assert_not_awaited()


@pytest.mark.parametrize("visibility", ["task_denied", "unassigned", "agent_denied"])
async def test_cards_follow_current_canonical_task_visibility_and_assignment(
    routing, monkeypatch, visibility
):
    link = SimpleNamespace(
        id=uuid4(), proposal_item_id=uuid4(), task_id=routing.task.id, accepted_revision=1
    )
    monkeypatch.setattr(
        module.routing_repo, "task_links", AsyncMock(return_value=[(link, routing.proposal)])
    )
    if visibility == "task_denied":
        routing.service.tasks.get.side_effect = NotFoundError()
    elif visibility == "unassigned":
        routing.task.assignee_agent_id = None
        routing.task.assignee_user_id = None
    else:
        routing.service.registry.get_runnable_spec.side_effect = AuthorizationError()
    result = await routing.service.task_cards(
        routing.ctx, routing.room.id, thread_root_message_id=None, limit=1
    )
    if visibility == "task_denied":
        assert result.items == []
    else:
        assert result.items[0].title == "Canonical title"
        assert result.items[0].agent is None
        assert "conversation_id" not in result.items[0].model_dump()
