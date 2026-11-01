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
