"""The shared state of what needs a person's attention, against Postgres (#2575)."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.notification import Notification, NotificationEventType
from app.db.models.notification_delivery import NotificationDelivery
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.outcome import Outcome
from app.db.models.suggestion import Suggestion
from app.db.models.user import User
from app.repositories import outcome_repo
from app.services.approvals import ApprovalService
from app.services.notification_center import NotificationCenterService
from app.services.notification_delivery import NotificationDeliveryService
from app.services.outcome import OutcomeService, cause_of

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _world(db: AsyncSession):
    users = [
        User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", full_name=n) for n in "AB"
    ]
    db.add_all(users)
    await db.flush()
    org = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=users[0].id
    )
    db.add(org)
    await db.flush()
    for user in users:
        db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="owner"))
    await db.flush()
    ctxs = [
        AuthContext(user_id=u.id, organization_id=org.id, role=OrgRoleName.OWNER) for u in users
    ]
    return org, users, ctxs


async def _run(db, org, user):
    """A real run with its chat: the outcome's links are foreign keys."""
    from app.db.models.agent import Agent, AgentVersion
    from app.db.models.agent_run import RunSurface
    from app.db.models.conversation import Conversation
    from app.repositories import agent_run_repo

    agent = Agent(
        organization_id=org.id,
        name="Finance",
        created_by_user_id=user.id,
        slug=f"a-{uuid.uuid4().hex[:8]}",
    )
    db.add(agent)
    await db.flush()
    version = AgentVersion(agent_id=agent.id, organization_id=org.id, version=1, spec={})
    chat = Conversation(organization_id=org.id, user_id=user.id, title="x")
    db.add_all([version, chat])
    await db.flush()
    run = await agent_run_repo.create_run(
        db,
        organization_id=org.id,
        agent_id=agent.id,
        agent_version_id=version.id,
        user_id=user.id,
        conversation_id=chat.id,
        surface=RunSurface.WEB.value,
        model_label="m",
        started_at=datetime.now(UTC),
    )
    await db.flush()
    return run, chat


async def _finding(db, org, user, occurrence, *, context=None, event=NotificationEventType.FINDING):
    (notification,) = await NotificationCenterService(db).write(
        recipients=[user.id],
        event_type=event,
        occurrence_id=occurrence,
        summary=f"Found {occurrence}",
        organization_id=org.id,
        render_context=context,
    )
    return notification


async def _reload(db, notification) -> Notification:
    """The row as the database has it: the write path hands back an untracked copy."""
    row = await db.scalar(
        select(Notification)
        .where(Notification.id == notification.id)
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return row


async def _deliveries(db, notification) -> list[NotificationDelivery]:
    result = await db.execute(
        select(NotificationDelivery).where(NotificationDelivery.notification_id == notification.id)
    )
    return list(result.scalars().all())


async def test_a_notification_that_is_somebodys_to_act_on_opens_an_outcome(
    db: AsyncSession,
) -> None:
    org, users, _ = await _world(db)
    run, chat = await _run(db, org, users[0])

    note = await _finding(
        db,
        org,
        users[0],
        "f1",
        context={"run_id": str(run.id), "conversation_id": str(chat.id)},
    )
    garbled = await _finding(db, org, users[0], "f2", context={"run_id": "bad"})
    news = await _finding(db, org, users[0], "r1", event=NotificationEventType.RUN_COMPLETED)

    assert note.outcome_id is not None and news.outcome_id is None
    outcome = await db.get(Outcome, note.outcome_id)
    assert outcome is not None
    assert (outcome.kind, outcome.status, outcome.summary) == ("finding", "open", "Found f1")
    assert outcome.source_run_id == run.id and outcome.source_conversation_id == chat.id
    loose = await db.get(Outcome, garbled.outcome_id)
    assert loose is not None and loose.source_run_id is None


async def test_one_cause_is_one_outcome_however_often_it_is_told(db: AsyncSession) -> None:
    org, users, _ = await _world(db)
    cause = {"cause": "nightly-report"}

    first = await _finding(db, org, users[0], "night-1", context=cause)
    second = await _finding(db, org, users[0], "night-2", context=cause)
    theirs = await _finding(db, org, users[1], "night-1", context=cause)

    assert first.outcome_id == second.outcome_id != theirs.outcome_id
    assert cause_of("finding", "x", {"cause": 3}) == "finding:x"
    assert cause_of("finding", "x", None) == "finding:x"


async def test_acknowledging_clears_what_has_not_gone_out_and_marks_it_read(
    db: AsyncSession,
) -> None:
    org, users, ctxs = await _world(db)
    note = await _finding(db, org, users[0], "f1")
    assert [d.status for d in await _deliveries(db, note)] == ["pending"]

    outcome = await OutcomeService(db).settle(ctxs[0], note.outcome_id, "acknowledge", via="chat")
    note = await _reload(db, note)

    assert (outcome.status, outcome.settled_via) == ("acknowledged", "chat")
    assert note.read_at is not None and note.dismissed_at is None
    (delivery,) = await _deliveries(db, note)
    await db.refresh(delivery)
    assert (delivery.status, delivery.last_error) == ("skipped", "outcome settled")
    assert await OutcomeService(db).settle(ctxs[0], note.outcome_id, "acknowledge", via="chat")


async def test_resolving_and_muting_close_it_and_final_states_do_not_flip(
    db: AsyncSession,
) -> None:
    org, users, ctxs = await _world(db)
    one = await _finding(db, org, users[0], "f1")
    two = await _finding(db, org, users[0], "f2")
    service = OutcomeService(db)

    await service.settle(ctxs[0], one.outcome_id, "acknowledge", via="inbox")
    resolved = await service.settle(ctxs[0], one.outcome_id, "resolve", via="inbox")
    muted = await service.settle(ctxs[0], two.outcome_id, "mute", via="inbox")
    one = await _reload(db, one)

    assert (resolved.status, muted.status) == ("resolved", "muted")
    assert one.dismissed_at is not None
    with pytest.raises(ConflictError) as flipped:
        await service.settle(ctxs[0], one.outcome_id, "mute", via="inbox")
    assert flipped.value.details == {"status": "resolved"}


async def test_somebody_elses_outcome_is_not_found(db: AsyncSession) -> None:
    org, users, ctxs = await _world(db)
    note = await _finding(db, org, users[0], "f1")

    with pytest.raises(NotFoundError):
        await OutcomeService(db).settle(ctxs[1], note.outcome_id, "resolve", via="inbox")
    with pytest.raises(NotFoundError):
        await OutcomeService(db).settle(ctxs[0], uuid.uuid4(), "resolve", via="inbox")


async def test_a_muted_cause_arrives_cleared_and_a_resolved_one_asks_again(
    db: AsyncSession,
) -> None:
    org, users, ctxs = await _world(db)
    service = OutcomeService(db)
    cause = {"cause": "nightly"}
    muted_first = await _finding(db, org, users[0], "m1", context=cause)
    await service.settle(ctxs[0], muted_first.outcome_id, "mute", via="inbox")

    again = await _finding(db, org, users[0], "m2", context=cause)

    assert again.dismissed_at is not None and again.read_at is not None
    assert await _deliveries(db, again) == []
    outcome = await db.get(Outcome, again.outcome_id)
    assert outcome is not None and outcome.status == "muted"

    other = {"cause": "weekly"}
    done = await _finding(db, org, users[0], "w1", context=other)
    await service.settle(ctxs[0], done.outcome_id, "resolve", via="inbox")
    back = await _finding(db, org, users[0], "w2", context=other)
    reopened = await db.get(Outcome, back.outcome_id)
    assert reopened is not None and reopened.status == "open" and reopened.settled_at is None
    assert back.dismissed_at is None


async def test_the_list_is_the_callers_own_open_outcomes_and_can_be_narrowed_to_a_chat(
    db: AsyncSession,
) -> None:
    org, users, ctxs = await _world(db)
    _, chat = await _run(db, org, users[0])
    in_chat = await _finding(db, org, users[0], "a", context={"conversation_id": str(chat.id)})
    elsewhere = await _finding(db, org, users[0], "b")
    await _finding(db, org, users[1], "c")
    service = OutcomeService(db)
    await service.settle(ctxs[0], elsewhere.outcome_id, "resolve", via="inbox")

    open_now = await service.list_mine(ctxs[0], open_only=True, conversation_id=None)
    everything = await service.list_mine(ctxs[0], open_only=False, conversation_id=None)
    from_chat = await service.list_mine(ctxs[0], open_only=False, conversation_id=chat.id)

    assert [o.id for o in open_now] == [in_chat.outcome_id]
    assert {o.id for o in everything} == {in_chat.outcome_id, elsewhere.outcome_id}
    assert [o.id for o in from_chat] == [in_chat.outcome_id]


async def test_a_delivery_that_was_claimed_just_before_the_outcome_settled_is_not_sent(
    db: AsyncSession,
) -> None:
    org, users, ctxs = await _world(db)
    note = await _finding(db, org, users[0], "f1")
    (delivery,) = await _deliveries(db, note)
    claimed_at = datetime.now(UTC)
    delivery.claimed_at = claimed_at
    await db.flush()
    outcome = await db.get(Outcome, note.outcome_id)
    outcome.status = "acknowledged"
    await db.flush()

    result = await NotificationDeliveryService(db).send_and_settle(
        delivery.id, claimed_at=claimed_at
    )

    assert result == "skipped"
    assert await outcome_repo.is_settled(db, outcome_id=note.outcome_id)
    assert not await outcome_repo.is_settled(db, outcome_id=uuid.uuid4())


async def test_deciding_the_last_approval_of_a_run_resolves_what_asked_about_it(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models.agent_run import ApprovalStatus
    from app.repositories import agent_run_repo

    org, users, ctxs = await _world(db)
    run, _ = await _run(db, org, users[0])
    run_id = run.id
    note = await _finding(
        db,
        org,
        users[0],
        "approval-1",
        context={"run_id": str(run_id)},
        event=NotificationEventType.APPROVAL_REQUESTED,
    )
    decided = SimpleNamespace(run_id=run_id, organization_id=org.id)
    pending = SimpleNamespace(status=ApprovalStatus.PENDING.value)
    settled = SimpleNamespace(status=ApprovalStatus.APPROVED.value)

    async def approvals(items):
        async def listed(*args, **kwargs):
            return items

        monkeypatch.setattr(agent_run_repo, "list_approvals_for_run", listed)

    service = ApprovalService(db)
    await approvals([pending, settled])
    await service._settle_outcomes(decided)
    still = await db.get(Outcome, note.outcome_id)
    assert still is not None and still.status == "open"

    await approvals([settled, settled])
    await service._settle_outcomes(decided)
    await db.refresh(still)
    assert (still.status, still.settled_via) == ("resolved", "approval")


async def test_a_caller_who_is_nobody_has_no_outcomes(db: AsyncSession) -> None:
    from app.core.exceptions import AuthorizationError

    org, _, _ = await _world(db)
    anonymous = AuthContext(user_id=None, organization_id=org.id, role=OrgRoleName.OWNER)

    with pytest.raises(AuthorizationError):
        await OutcomeService(db).list_mine(anonymous, open_only=True, conversation_id=None)
    with pytest.raises(AuthorizationError):
        await OutcomeService(db).settle(anonymous, uuid.uuid4(), "resolve", via="inbox")


async def _watch_finding(db: AsyncSession, org: Organization, user: User) -> Suggestion:
    from app.repositories import suggestion_repo

    finding = await suggestion_repo.propose(
        db,
        organization_id=org.id,
        user_id=user.id,
        kind="finding",
        title="Review contract",
        detail="A watch found a change",
        payload={},
        dedupe_key=uuid.uuid4().hex,
    )
    assert finding is not None
    return finding


@pytest.mark.parametrize("action,expected", [("resolve", "accepted"), ("mute", "dismissed")])
async def test_settling_a_chat_finding_projects_into_the_inbox_and_stops_delivery(
    db: AsyncSession,
    action: str,
    expected: str,
) -> None:
    org, users, ctxs = await _world(db)
    run, chat = await _run(db, org, users[0])
    finding = await _watch_finding(db, org, users[0])
    service = OutcomeService(db)
    case = await service.track_finding(finding, run_id=run.id, conversation_id=chat.id)
    assert finding.outcome_id == case.id
    assert case.source_conversation_id == chat.id
    note = await _finding(db, org, users[0], str(finding.id))
    assert note.outcome_id == case.id
    assert [d.status for d in await _deliveries(db, note)] == ["pending"]
    await service.settle(ctxs[0], case.id, action, via="chat")
    await db.refresh(finding)
    assert finding.status == expected
    assert finding.outcome_status == case.status
    for delivery in await _deliveries(db, note):
        await db.refresh(delivery)
        assert delivery.status == "skipped"
    repeated = await service.track_finding(finding)
    assert repeated.id == case.id and repeated.status != "open"


async def test_acknowledging_a_finding_keeps_it_to_do_then_inbox_resolution_closes_same_case(
    db: AsyncSession,
) -> None:
    from app.services.suggestions import SuggestionService

    org, users, ctxs = await _world(db)
    finding = await _watch_finding(db, org, users[0])
    case = await OutcomeService(db).track_finding(finding)
    await OutcomeService(db).settle(ctxs[0], case.id, "acknowledge", via="chat")
    await db.refresh(finding)
    assert (finding.status, finding.outcome_status) == ("open", "acknowledged")
    result = await SuggestionService(db).accept(ctxs[0], finding.id)
    assert (result.status, result.outcome_status) == ("accepted", "resolved")
    assert result.outcome_id == case.id


async def test_dismiss_and_explicit_undo_reuse_the_finding_case_without_replaying_sends(
    db: AsyncSession,
) -> None:
    from app.services.suggestions import SuggestionService

    org, users, ctxs = await _world(db)
    finding = await _watch_finding(db, org, users[0])
    note = await _finding(db, org, users[0], str(finding.id))
    service = SuggestionService(db)
    dismissed = await service.dismiss(ctxs[0], finding.id)
    assert (dismissed.status, dismissed.outcome_status) == ("dismissed", "muted")
    restored = await service.restore(ctxs[0], finding.id)
    assert (restored.status, restored.outcome_status) == ("open", "open")
    assert restored.outcome_id == note.outcome_id
    for delivery in await _deliveries(db, note):
        await db.refresh(delivery)
        assert delivery.status == "skipped"
    with pytest.raises(NotFoundError):
        await service.accept(ctxs[1], finding.id)
    await db.refresh(finding)
    assert finding.status == "open"


async def test_acknowledged_findings_are_not_announced_again_by_the_daily_briefing(
    db: AsyncSession,
) -> None:
    from app.repositories import suggestion_repo

    org, users, ctxs = await _world(db)
    finding = await _watch_finding(db, org, users[0])
    case = await OutcomeService(db).track_finding(finding)
    assert await suggestion_repo.unbriefed_findings(db, organization_id=org.id, user_id=users[0].id)
    await OutcomeService(db).settle(ctxs[0], case.id, "acknowledge", via="chat")
    assert not await suggestion_repo.unbriefed_findings(
        db, organization_id=org.id, user_id=users[0].id
    )
    assert await suggestion_repo.list_open(db, organization_id=org.id, user_id=users[0].id)


async def test_a_rolled_back_finding_decision_rolls_back_its_inbox_and_delivery_state(
    db: AsyncSession,
) -> None:
    from app.services.suggestions import SuggestionService

    org, users, ctxs = await _world(db)
    finding = await _watch_finding(db, org, users[0])
    note = await _finding(db, org, users[0], str(finding.id))
    async with db.begin_nested() as savepoint:
        await SuggestionService(db).dismiss(ctxs[0], finding.id)
        await savepoint.rollback()
    await db.refresh(finding)
    assert (finding.status, finding.outcome_status) == ("open", "open")
    for delivery in await _deliveries(db, note):
        await db.refresh(delivery)
        assert delivery.status == "pending"


async def test_deleting_a_watch_settles_only_its_owners_cases_before_removing_findings(
    db: AsyncSession,
) -> None:
    from app.db.models.mcp_connection import McpConnection
    from app.db.models.watch import Watch
    from app.services.watches import WatchService

    org, users, ctxs = await _world(db)
    connection = McpConnection(
        user_id=users[0].id,
        scope="user",
        purpose="mcp",
        name="GitHub",
        catalog_key="github",
        url="https://github.example/mcp",
        is_enabled=True,
    )
    db.add(connection)
    await db.flush()
    watch = Watch(
        organization_id=org.id,
        user_id=users[0].id,
        connection_id=connection.id,
        title="Reviews",
        instructions="Reviews waiting on me",
        interval_minutes=60,
        next_run_at=datetime.now(UTC),
    )
    db.add(watch)
    await db.flush()
    finding = await _watch_finding(db, org, users[0])
    finding.watch_id = watch.id
    await db.flush()
    case = await OutcomeService(db).track_finding(finding)
    other = await _watch_finding(db, org, users[1])
    other_case = await OutcomeService(db).track_finding(other)
    note = await _finding(db, org, users[0], str(finding.id))
    decided = await _watch_finding(db, org, users[0])
    decided.watch_id = watch.id
    await db.flush()
    decided_case = await OutcomeService(db).track_finding(decided)
    await OutcomeService(db).settle(ctxs[0], decided_case.id, "mute", via="chat")
    finding_id = finding.id
    await WatchService(db).delete(ctxs[0], watch.id)
    await db.refresh(case)
    assert (case.status, case.settled_via) == ("resolved", "watch")
    assert await db.scalar(select(Suggestion.id).where(Suggestion.id == finding_id)) is None
    await db.refresh(other_case)
    assert other_case.status == "open"
    await db.refresh(decided_case)
    assert decided_case.status == "muted"
    for delivery in await _deliveries(db, note):
        await db.refresh(delivery)
        assert delivery.status == "skipped"


async def test_finding_cases_reject_wrong_kind_scope_identity_and_unasked_restore(
    db: AsyncSession,
) -> None:
    from dataclasses import replace

    org, users, ctxs = await _world(db)
    finding = await _watch_finding(db, org, users[0])
    service = OutcomeService(db)
    finding.kind = "routine"
    with pytest.raises(ConflictError, match="Only a finding"):
        await service.track_finding(finding)
    finding.kind = "finding"
    for ctx in (ctxs[1], replace(ctxs[0], organization_id=uuid.uuid4())):
        with pytest.raises(NotFoundError):
            await service.restore_finding(ctx, finding)
    case = await service.track_finding(finding)
    with pytest.raises(NotFoundError, match="dismissed"):
        await service.restore_finding(ctxs[0], finding)
    different = await _watch_finding(db, org, users[0])
    other_case = await service.track_finding(different)
    different.outcome_id = None
    await db.flush()
    finding.outcome_id = other_case.id
    await db.flush()
    with pytest.raises(ConflictError, match="different outcome"):
        await service.track_finding(finding)
    finding.outcome_id = case.id
    await db.flush()


async def test_tracking_an_old_decided_finding_closes_its_preexisting_open_case(
    db: AsyncSession,
) -> None:
    org, users, _ = await _world(db)
    finding = await _watch_finding(db, org, users[0])
    finding.status = "dismissed"
    await db.flush()
    case = await OutcomeService(db).track_finding(finding)
    assert case.status == "resolved"
    await db.refresh(finding)
    assert finding.status == "dismissed"


@pytest.mark.parametrize(
    "access", ["allowed", "other-owner", "other-organization", "inactive", "database-error"]
)
async def test_routine_console_delivery_uses_current_access_and_isolates_database_failures(
    db: AsyncSession,
    access: str,
) -> None:
    from unittest.mock import patch

    from sqlalchemy import text, update

    from app.db.models.agent import Agent
    from app.db.models.agent_trigger import AgentTrigger
    from app.db.models.conversation import Message
    from app.services.agent_trigger import AgentTriggerService

    org, users, _ = await _world(db)
    run, chat = await _run(db, org, users[0])
    agent = await db.get(Agent, run.agent_id)
    assert agent is not None
    trigger = AgentTrigger(
        organization_id=org.id,
        agent_id=agent.id,
        created_by_user_id=users[0].id,
        prompt="Report",
        trigger_type="schedule",
        schedule_kind="interval",
        interval_seconds=600,
        next_fire_at=datetime.now(UTC),
        answer_to="conversation",
        delivery_conversation_id=chat.id,
    )
    db.add(trigger)
    if access == "other-owner":
        await db.execute(
            update(type(chat))
            .where(type(chat).id == chat.id)
            .values(user_id=users[1].id)
            .execution_options(synchronize_session=False)
        )
    elif access == "other-organization":
        other_org, _, _ = await _world(db)
        await db.execute(
            update(type(chat))
            .where(type(chat).id == chat.id)
            .values(organization_id=other_org.id)
            .execution_options(synchronize_session=False)
        )
    elif access == "inactive":
        users[0].is_active = False
    await db.flush()

    async def database_error(*args: object, **kwargs: object) -> None:
        await db.execute(text("SELECT 1 / 0"))

    if access == "database-error":
        with patch(
            "app.services.agent_trigger.conversation_repo.create_message", new=database_error
        ):
            delivery = await AgentTriggerService(db)._deliver(
                trigger, agent=agent, run=run, answer="Report ready"
            )
    else:
        delivery = await AgentTriggerService(db)._deliver(
            trigger, agent=agent, run=run, answer="Report ready"
        )
    assert delivery.status == ("delivered" if access == "allowed" else "unavailable")
    assert delivery.conversation_id == (chat.id if access == "allowed" else None)
    from app.schemas.agent_trigger import TriggerRead

    trigger.last_delivery_status = delivery.status.value
    await db.flush()
    await db.refresh(trigger)
    assert TriggerRead.model_validate(trigger).last_delivery_status == delivery.status
    assert await db.scalar(text("SELECT 1")) == 1
    messages = list(await db.scalars(select(Message).where(Message.conversation_id == chat.id)))
    assert len(messages) == (1 if access == "allowed" else 0)


async def test_delivery_membership_reads_do_not_reuse_a_role_cached_before_the_run(
    db: AsyncSession,
) -> None:
    from sqlalchemy import update

    from app.repositories import member_repo

    org, users, _ = await _world(db)
    cached = await member_repo.get_active(db, organization_id=org.id, user_id=users[0].id)
    assert cached is not None and cached.role == "owner"
    await db.execute(
        update(OrganizationMember)
        .where(
            OrganizationMember.organization_id == org.id,
            OrganizationMember.user_id == users[0].id,
        )
        .values(role="viewer")
        .execution_options(synchronize_session=False)
    )
    current = await member_repo.get_active(db, organization_id=org.id, user_id=users[0].id)
    assert current is cached and current.role == "viewer"


async def test_reopened_cause_moves_to_the_new_incidents_chat(db: AsyncSession) -> None:
    org, users, ctxs = await _world(db)
    first_run, first_chat = await _run(db, org, users[0])
    next_run, next_chat = await _run(db, org, users[0])
    first = await _finding(
        db,
        org,
        users[0],
        "old-incident",
        context={
            "cause": "recurring",
            "run_id": str(first_run.id),
            "conversation_id": str(first_chat.id),
        },
    )
    await OutcomeService(db).settle(ctxs[0], first.outcome_id, "resolve", via="chat")
    again = await _finding(
        db,
        org,
        users[0],
        "new-incident",
        context={
            "cause": "recurring",
            "run_id": str(next_run.id),
            "conversation_id": str(next_chat.id),
        },
    )
    row = await db.get(Outcome, again.outcome_id)
    assert row is not None and row.id == first.outcome_id
    assert row.source_run_id == next_run.id and row.source_conversation_id == next_chat.id
    assert row.summary == "Found new-incident" and row.status == "open"


async def test_stale_approval_sweep_resolves_its_case_and_pending_deliveries(
    db: AsyncSession,
) -> None:
    from datetime import timedelta

    from app.core.config import settings
    from app.db.models.agent_run import ToolApproval

    org, users, _ = await _world(db)
    run, _ = await _run(db, org, users[0])
    run.status = "awaiting_approval"
    approval = ToolApproval(
        organization_id=org.id,
        run_id=run.id,
        agent_id=run.agent_id,
        tool_id="send_email",
        tool_args={},
        status="pending",
        created_at=datetime.now(UTC) - timedelta(hours=settings.APPROVAL_EXPIRY_HOURS + 1),
    )
    db.add(approval)
    await db.flush()
    note = await _finding(
        db,
        org,
        users[0],
        "approval-timeout",
        context={"run_id": str(run.id)},
        event=NotificationEventType.APPROVAL_REQUESTED,
    )
    expired = await ApprovalService(db).expire_stale()
    assert expired == 1
    row = await db.get(Outcome, note.outcome_id)
    assert row is not None and row.status == "resolved" and row.settled_via == "expiry"
    assert approval.status == "expired" and run.status == "cancelled"
    assert all(item.status == "skipped" for item in await _deliveries(db, note))


async def test_routine_findings_keep_one_private_chat_and_case_across_revisions(db: AsyncSession):
    from app.db.models.conversation import Conversation, Message
    from app.schemas.routine_notifications import RoutineFinding
    from app.services.routine_delivery import RoutineFindingService

    org, users, contexts = await _world(db)
    run, _ = await _run(db, org, users[0])
    origin = uuid.uuid4()
    service = RoutineFindingService(db)
    first = RoutineFinding(
        key="mail-thread-1",
        revision="message-1",
        title="Reply to Acme",
        content="Draft: Friday works for us.",
    )
    args = {
        "run": run,
        "user_id": users[0].id,
        "origin_id": origin,
        "origin_kind": "trigger",
        "notify": False,
    }
    chat_id = await service.publish(**args, item=first)
    assert chat_id is not None
    chat = await db.get(Conversation, chat_id)
    assert chat.user_id == users[0].id
    assert chat.organization_id == org.id
    cases = await OutcomeService(db).list_mine(contexts[0], open_only=True, conversation_id=chat_id)
    assert len(cases) == 1
    assert cases[0].context_url == f"/chat/{chat_id}"
    source = (await OutcomeService(db).finding_sources(contexts[0], cases))[cases[0].id]
    assert (source.item_id, source.revision) == ("mail-thread-1", "message-1")
    assert (
        await OutcomeService(db).list_mine(contexts[1], open_only=True, conversation_id=chat_id)
        == []
    )
    assert await service.publish(**args, item=first) is None
    await OutcomeService(db).settle(contexts[0], cases[0].id, "resolve", via="chat")
    second = first.model_copy(
        update={"revision": "message-2", "content": "Updated draft: Monday works."}
    )
    assert await service.publish(**args, item=second) == chat_id
    assert cases[0].status == "open"
    assert (
        await service.publish(**args, item=first) is None
    )  # Old deliveries never reopen old drafts.
    messages = list(
        await db.scalars(
            select(Message).where(Message.conversation_id == chat_id).order_by(Message.created_at)
        )
    )
    assert len(messages) == 2
    assert "Friday" in messages[0].content
    assert "Monday" in messages[1].content
    assert (
        len(list(await db.scalars(select(Suggestion).where(Suggestion.user_id == users[0].id))))
        == 1
    )
    await OutcomeService(db).settle(contexts[0], cases[0].id, "mute", via="inbox")
    assert (
        await service.publish(**args, item=first.model_copy(update={"revision": "message-3"}))
        is None
    )


async def test_routine_findings_deliver_new_revisions_once_and_respect_shared_settlement(
    db: AsyncSession,
):
    from app.schemas.routine_notifications import RoutineFinding
    from app.services.routine_delivery import RoutineFindingService

    org, users, contexts = await _world(db)
    run, _ = await _run(db, org, users[0])
    service = RoutineFindingService(db)
    origin = uuid.uuid4()
    item = RoutineFinding(
        key="thread", revision="mail-1", title="Check draft", content="Draft awaiting review."
    )
    args = {"run": run, "user_id": users[0].id, "origin_id": origin, "origin_kind": "trigger"}
    chat_id = await service.publish(**args, item=item)
    case = (
        await OutcomeService(db).list_mine(contexts[0], open_only=True, conversation_id=chat_id)
    )[0]
    await service.publish(**args, item=item)
    notices = list(await db.scalars(select(Notification).where(Notification.outcome_id == case.id)))
    assert len(notices) == 1
    await OutcomeService(db).settle(contexts[0], case.id, "resolve", via="chat")
    await service.publish(**args, item=item.model_copy(update={"revision": "mail-2"}))
    notices = list(
        await db.scalars(
            select(Notification)
            .where(Notification.outcome_id == case.id)
            .order_by(Notification.created_at)
        )
    )
    assert len(notices) == 2
    assert notices[0].dismissed_at is not None
    assert notices[1].dismissed_at is None
    assert case.status == "open"


async def test_overlapping_routine_findings_publish_one_chat(db: AsyncSession):
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models.agent_run import AgentRun
    from app.schemas.routine_notifications import RoutineFinding
    from app.services.routine_delivery import RoutineFindingService

    org, users, _ = await _world(db)
    run, _ = await _run(db, org, users[0])
    run_id, user_id, origin_id = run.id, users[0].id, uuid.uuid4()
    await db.commit()
    sessions = async_sessionmaker(db.bind, expire_on_commit=False)
    item = RoutineFinding(
        key="same-thread", revision="same-message", title="Reply", content="Draft awaiting review."
    )

    async def publish() -> uuid.UUID | None:
        async with sessions() as session:
            current = await session.get(AgentRun, run_id)
            assert current is not None
            target = await RoutineFindingService(session).publish(
                run=current,
                user_id=user_id,
                origin_id=origin_id,
                origin_kind="trigger",
                item=item,
                notify=False,
            )
            await session.commit()
            return target

    results = await asyncio.gather(publish(), publish())
    assert sum(target is not None for target in results) == 1
    assert len(list(await db.scalars(select(Suggestion).where(Suggestion.user_id == user_id)))) == 1


async def test_an_unavailable_working_chat_does_not_consume_a_new_source_revision(db: AsyncSession):
    from app.db.models.conversation import Conversation
    from app.schemas.routine_notifications import RoutineFinding
    from app.services.routine_delivery import RoutineFindingService

    org, users, _ = await _world(db)
    run, _ = await _run(db, org, users[0])
    service = RoutineFindingService(db)
    item = RoutineFinding(
        key="thread",
        revision="first",
        title="Draft",
        content="Proposal",
        url="https://mail.example/thread",
    )
    args = {
        "run": run,
        "user_id": users[0].id,
        "origin_id": uuid.uuid4(),
        "origin_kind": "trigger",
        "notify": False,
    }
    target = await service.publish(**args, item=item)
    chat = await db.get(Conversation, target)
    assert chat is not None
    chat.is_archived = True
    await db.flush()
    next_item = item.model_copy(update={"revision": "next"})
    with pytest.raises(ConflictError):
        async with db.begin_nested():
            await service.publish(**args, item=next_item)
    await db.refresh(chat)
    chat.is_archived = False
    await db.flush()
    assert await service.publish(**args, item=next_item) == target
