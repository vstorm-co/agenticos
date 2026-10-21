"""Asynchronous API runs: queued with what was asked, read back by whoever asked (#2219).

Against the real queue, because the guarantees are its: an `Idempotency-Key`
holds by a unique index, so a retry is the same request and never a second run;
a request is the asker's alone; and what the worker finished with is what the
poll reads. The conversation lookup and the attachments are stubbed - they have
their own tests - so the queue is what is under test.
"""

import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AlreadyExistsError, AuthenticationError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.background_job import BackgroundJob
from app.db.models.conversation import Conversation
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import background_job as job_repo
from app.schemas.agent import AgentRunRequest
from app.services.api_runs import ApiRunService, digest, scoped_key
from app.worker.jobs import RUN_AGENT

pytestmark = pytest.mark.anyio

CONVERSATION = uuid.uuid4()


@pytest.fixture
def stubbed():
    with (
        patch(
            "app.services.api_runs.ConversationService.for_api_run",
            new=AsyncMock(return_value=(CONVERSATION, None)),
        ),
        patch("app.services.api_runs.load_attached_files", new=AsyncMock(return_value=[])),
        patch(
            "app.services.api_runs.AgentRegistryService.get_runnable_spec",
            new=AsyncMock(return_value=None),
        ),
    ):
        yield


async def _person(db: AsyncSession, *, role: str = "member") -> AuthContext:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role=role))
    await db.flush()
    return AuthContext(user_id=user.id, organization_id=org.id, role=role)


def _ask(prompt: str = "How do I rotate a key?") -> AgentRunRequest:
    return AgentRunRequest(prompt=prompt)


async def test_a_queued_run_is_known_at_once_and_carries_the_asker(
    db: AsyncSession, stubbed
) -> None:
    ctx = await _person(db)
    agent_id = uuid.uuid4()

    queued = await ApiRunService(db).queue(ctx, agent_id, _ask(), idempotency_key=None)

    assert (queued.status, queued.conversation_id, queued.result) == ("queued", CONVERSATION, None)
    job = await job_repo.get(db, queued.id)
    assert job is not None
    payload = RUN_AGENT.load(job.payload)
    assert (payload.agent_id, payload.user_id, payload.api_key_id) == (agent_id, ctx.user_id, None)
    assert (job.pool, job.max_attempts, job.organization_id) == ("agent", 1, ctx.organization_id)


async def test_a_retry_under_the_same_key_is_the_same_request(db: AsyncSession, stubbed) -> None:
    ctx = await _person(db)
    agent_id = uuid.uuid4()
    service = ApiRunService(db)

    first = await service.queue(ctx, agent_id, _ask(), idempotency_key="order-7")
    again = await service.queue(ctx, agent_id, _ask(), idempotency_key="order-7")

    assert again.id == first.id


async def test_the_same_key_for_a_different_request_is_refused(db: AsyncSession, stubbed) -> None:
    ctx = await _person(db)
    agent_id = uuid.uuid4()
    service = ApiRunService(db)
    await service.queue(ctx, agent_id, _ask(), idempotency_key="order-7")

    with pytest.raises(AlreadyExistsError, match="different request"):
        await service.queue(ctx, agent_id, _ask("something else"), idempotency_key="order-7")


async def test_a_run_of_an_agent_the_caller_may_not_run_is_refused_before_it_is_queued(
    db: AsyncSession,
) -> None:
    """Codex P1 on #2248: refused by the worker, the job sat queued with its payload."""
    ctx = await _person(db)
    with (
        patch(
            "app.services.api_runs.AgentRegistryService.get_runnable_spec",
            new=AsyncMock(side_effect=NotFoundError(message="Agent not found")),
        ),
        pytest.raises(NotFoundError),
    ):
        await ApiRunService(db).queue(ctx, uuid.uuid4(), _ask(), idempotency_key=None)

    queued = await db.execute(select(BackgroundJob).where(BackgroundJob.kind == RUN_AGENT.kind))
    assert queued.scalars().all() == []


async def test_keys_are_per_organization(db: AsyncSession, stubbed) -> None:
    one, other = await _person(db), await _person(db)
    agent_id = uuid.uuid4()

    a = await ApiRunService(db).queue(one, agent_id, _ask(), idempotency_key="order-7")
    b = await ApiRunService(db).queue(other, agent_id, _ask(), idempotency_key="order-7")

    assert a.id != b.id


async def test_keys_are_per_person_inside_one_organization(db: AsyncSession, stubbed) -> None:
    """A colleague who sends the same key neither reads the run nor blocks the key."""
    asker = await _person(db)
    colleague = AuthContext(
        user_id=uuid.uuid4(), organization_id=asker.organization_id, role="member"
    )
    db.add(
        User(id=colleague.subject_id, email=f"{uuid.uuid4().hex}@example.com", hashed_password="x")
    )
    await db.flush()
    agent_id = uuid.uuid4()

    mine = await ApiRunService(db).queue(asker, agent_id, _ask(), idempotency_key="order-7")
    theirs = await ApiRunService(db).queue(
        colleague, agent_id, _ask("something else"), idempotency_key="order-7"
    )

    assert mine.id != theirs.id
    stored = await job_repo.get(db, mine.id)
    assert stored is not None and stored.idempotency_key == scoped_key(asker, "order-7")
    assert "order-7" not in stored.idempotency_key


async def test_a_lost_race_on_the_key_answers_as_the_winners_replay(
    db: AsyncSession, stubbed
) -> None:
    """The lookup missed, then the insert met the unique index: the winner's request comes back."""
    ctx = await _person(db)
    agent_id = uuid.uuid4()
    service = ApiRunService(db)
    winner = await service.queue(ctx, agent_id, _ask(), idempotency_key="order-7")

    real_lookup = job_repo.get_by_idempotency_key
    calls = 0

    async def misses_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        return None if calls == 1 else await real_lookup(*args, **kwargs)

    with patch("app.services.api_runs.background_job_repo.get_by_idempotency_key", new=misses_once):
        loser = await service.queue(ctx, agent_id, _ask(), idempotency_key="order-7")

    assert loser.id == winner.id


async def test_a_lost_race_takes_back_the_conversation_it_opened(db: AsyncSession) -> None:
    """Both racers open a conversation before the insert; the loser's must not stay
    behind as an empty chat in the caller's sidebar."""
    ctx = await _person(db)
    agent_id = uuid.uuid4()
    opened: list[uuid.UUID] = []

    async def opens(_self, ctx, _conversation_id, *, prompt):
        conversation = Conversation(
            id=uuid.uuid4(),
            user_id=ctx.user_id,
            organization_id=ctx.organization_id,
            title=prompt[:40],
        )
        db.add(conversation)
        await db.flush()
        opened.append(conversation.id)
        return conversation.id, None

    real_lookup = job_repo.get_by_idempotency_key
    calls = 0

    async def misses_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        return None if calls == 2 else await real_lookup(*args, **kwargs)

    with (
        patch("app.services.api_runs.ConversationService.for_api_run", new=opens),
        patch("app.services.api_runs.load_attached_files", new=AsyncMock(return_value=[])),
        patch(
            "app.services.api_runs.AgentRegistryService.get_runnable_spec",
            new=AsyncMock(return_value=None),
        ),
        patch("app.services.api_runs.background_job_repo.get_by_idempotency_key", new=misses_once),
    ):
        service = ApiRunService(db)
        winner = await service.queue(ctx, agent_id, _ask(), idempotency_key="order-8")
        loser = await service.queue(ctx, agent_id, _ask(), idempotency_key="order-8")

    assert loser.id == winner.id
    assert len(opened) == 2
    kept = (
        (await db.execute(select(Conversation.id).where(Conversation.id.in_(opened))))
        .scalars()
        .all()
    )
    assert kept == [opened[0]]


async def test_only_the_asker_reads_the_request(db: AsyncSession, stubbed) -> None:
    ctx = await _person(db)
    queued = await ApiRunService(db).queue(ctx, uuid.uuid4(), _ask(), idempotency_key=None)
    colleague = AuthContext(user_id=uuid.uuid4(), organization_id=ctx.organization_id, role="admin")
    stranger = await _person(db)

    assert (await ApiRunService(db).get(ctx, queued.id)).id == queued.id
    for outsider in (colleague, stranger):
        with pytest.raises(NotFoundError):
            await ApiRunService(db).get(outsider, queued.id)
    with pytest.raises(NotFoundError):
        await ApiRunService(db).get(ctx, uuid.uuid4())


async def test_a_job_that_is_not_a_run_request_is_not_one(db: AsyncSession) -> None:
    ctx = await _person(db)
    other = await job_repo.add(
        db,
        kind="expire-approvals",
        pool="system",
        payload={},
        max_attempts=1,
        priority=1,
        organization_id=ctx.organization_id,
    )
    assert other is not None
    with pytest.raises(NotFoundError):
        await ApiRunService(db).get(ctx, other)


async def test_the_poll_reads_what_the_worker_finished_with(db: AsyncSession, stubbed) -> None:
    ctx = await _person(db)
    queued = await ApiRunService(db).queue(ctx, uuid.uuid4(), _ask(), idempotency_key=None)
    claimed = await job_repo.claim(db, pool="agent", worker_id="w", lease=timedelta(minutes=1))
    assert claimed is not None
    assert (await ApiRunService(db).get(ctx, queued.id)).status == "running"

    answer = {
        "run_id": str(uuid.uuid4()),
        "conversation_id": str(CONVERSATION),
        "output": "Rotate it in the vault.",
        "status": "completed",
        "cost_usd": "0.0031",
        "input_tokens": 120,
        "output_tokens": 40,
    }
    await job_repo.complete(db, queued.id, fence=claimed.attempts, result=answer)

    done = await ApiRunService(db).get(ctx, queued.id)
    assert done.status == "completed"
    assert done.result is not None
    assert (done.result.output, done.result.cost_usd) == (
        "Rotate it in the vault.",
        Decimal("0.0031"),
    )


async def test_a_conversations_runs_are_claimed_one_at_a_time(db: AsyncSession, stubbed) -> None:
    """Codex on #2248: two runs of one thread claimed at once, the second read the
    history before the first answer was written, and both wrote into the thread.

    Which is claimed first is not asserted: both are queued in this test's one
    transaction, so they share `run_after` and the tie falls to the id. A real
    follow-up is a later request, and a later transaction, so it queues behind.
    """
    ctx = await _person(db)
    first = await ApiRunService(db).queue(ctx, uuid.uuid4(), _ask(), idempotency_key=None)
    follow_up = await ApiRunService(db).queue(
        ctx, uuid.uuid4(), _ask("And then?"), idempotency_key=None
    )
    assert first.conversation_id == follow_up.conversation_id

    claimed = await job_repo.claim(db, pool="agent", worker_id="w", lease=timedelta(minutes=1))
    assert claimed is not None and claimed.id in {first.id, follow_up.id}
    assert (
        await job_repo.claim(db, pool="agent", worker_id="w2", lease=timedelta(minutes=1)) is None
    )

    await job_repo.complete(db, claimed.id, fence=claimed.attempts, result={})
    other = await job_repo.claim(db, pool="agent", worker_id="w2", lease=timedelta(minutes=1))
    assert other is not None and {claimed.id, other.id} == {first.id, follow_up.id}


async def test_a_run_that_died_reads_as_failed_with_why(db: AsyncSession, stubbed) -> None:
    ctx = await _person(db)
    queued = await ApiRunService(db).queue(ctx, uuid.uuid4(), _ask(), idempotency_key=None)
    await job_repo.claim(db, pool="agent", worker_id="w", lease=timedelta(seconds=-1))
    await job_repo.rescue_expired(db, retry_in=timedelta(0))

    failed = await ApiRunService(db).get(ctx, queued.id)
    assert failed.status == "failed"
    assert failed.error is not None
    assert "worker lost" in failed.error


async def test_the_worker_runs_as_the_asker_is_now_and_answers_the_synchronous_result(
    db: AsyncSession, stubbed
) -> None:
    ctx = await _person(db, role="admin")
    queued = await ApiRunService(db).queue(ctx, uuid.uuid4(), _ask(), idempotency_key=None)
    job = await job_repo.get(db, queued.id)
    assert job is not None
    run = SimpleNamespace(
        id=uuid.uuid4(),
        status="completed",
        cost_usd=Decimal("0.01"),
        cost_is_partial=False,
        input_tokens=10,
        output_tokens=5,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )
    execute = AsyncMock(return_value=("Done.", run))
    with (
        patch("app.services.api_runs.AgentRunnerService.execute", new=execute),
        patch(
            "app.services.api_runs.AgentRunnerService.parked_calls", new=AsyncMock(return_value=[])
        ),
    ):
        result = await ApiRunService(db).run(RUN_AGENT.load(job.payload))

    assert (result.output, result.run_id, result.conversation_id) == ("Done.", run.id, CONVERSATION)
    ran_as = execute.await_args.args[0]
    assert (ran_as.user_id, ran_as.role, ran_as.api_key_id) == (ctx.user_id, "admin", None)


async def test_a_person_no_longer_a_member_when_the_run_starts_is_refused(
    db: AsyncSession, stubbed
) -> None:
    ctx = await _person(db)
    queued = await ApiRunService(db).queue(ctx, uuid.uuid4(), _ask(), idempotency_key=None)
    job = await job_repo.get(db, queued.id)
    assert job is not None
    payload = RUN_AGENT.load(job.payload).model_copy(update={"user_id": uuid.uuid4()})

    with pytest.raises(AuthenticationError):
        await ApiRunService(db).run(payload)


async def test_a_key_revoked_while_its_run_waited_does_not_run_it(
    db: AsyncSession, stubbed
) -> None:
    ctx = await _person(db)
    queued = await ApiRunService(db).queue(ctx, uuid.uuid4(), _ask(), idempotency_key=None)
    job = await job_repo.get(db, queued.id)
    assert job is not None
    gone_key = RUN_AGENT.load(job.payload).model_copy(update={"api_key_id": uuid.uuid4()})

    with pytest.raises(AuthenticationError):
        await ApiRunService(db).run(gone_key)


def test_the_fingerprint_is_the_agent_and_the_body() -> None:
    agent = uuid.uuid4()
    assert digest(agent, _ask()) == digest(agent, _ask())
    assert digest(agent, _ask()) != digest(uuid.uuid4(), _ask())
    assert digest(agent, _ask()) != digest(agent, _ask("other"))
