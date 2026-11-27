"""Focused queue-idempotency and worker-admission tests for API agent runs.

`tests/integration/test_api_run_requests.py` loses the race for real against the
unique index; the lines after the lost insert are pinned here as well, because
the coverage tracer does not always record lines after an `await` in an
`except` reached through a real database error.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestContext, ModelRequestParameters
from pydantic_ai.models.test import TestModel
from sqlalchemy.exc import IntegrityError

from app.agents.capabilities.guardrails import GuardrailBlocked, GuardrailsConfig, input_screen
from app.agents.deps import AgentDeps
from app.agents.steering import Steering, SteeringInbox
from app.core.exceptions import AuthenticationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.schemas.agent import AgentRunRequest
from app.services import api_runs
from app.services.api_runs import ApiRunService, digest
from app.worker.jobs import RUN_AGENT, RunAgent

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "case",
    [
        "lease_lost",
        "no_correction",
        "revoked_key",
        "changed_role",
        "version_changed",
        "run_gone",
        "lost_access",
        "blocked",
        "redacted",
    ],
)
async def test_only_a_screened_and_authorized_correction_is_consumed(
    monkeypatch, case: str
) -> None:
    db = MagicMock()
    started = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="admin")
    parent = RunAgent(
        agent_id=uuid.uuid4(),
        organization_id=started.organization_id,
        user_id=started.subject_id,
        api_key_id=None,
        conversation_id=uuid.uuid4(),
        environment_id=None,
        prompt="go",
        file_ids=[],
        digest="original",
        execution_token=uuid.uuid4(),
    )
    text = "salary" if case == "blocked" else "use key sk-ant-api03-" + "x" * 90
    correction = parent.model_copy(update={"prompt": text, "steer_target": parent.execution_token})
    row = SimpleNamespace(id=uuid.uuid4(), payload=RUN_AGENT.dump(correction))

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(api_runs, "get_db_context", session)
    monkeypatch.setattr(
        api_runs.background_job_repo,
        "lock_api_steering_target",
        AsyncMock(return_value=case != "lease_lost"),
    )
    pending = AsyncMock(return_value=[] if case == "no_correction" else [row])
    monkeypatch.setattr(api_runs.background_job_repo, "queued_api_steers", pending)
    finish = AsyncMock()
    monkeypatch.setattr(api_runs.background_job_repo, "finish_run_addition", finish)
    context = AsyncMock(
        side_effect=AuthenticationError(message="revoked") if case == "revoked_key" else None,
        return_value=replace(started, role="viewer") if case == "changed_role" else started,
    )
    monkeypatch.setattr(ApiRunService, "_context", context)
    version_id = uuid.uuid4()
    monkeypatch.setattr(
        api_runs.AgentRegistryService,
        "get_runnable_spec",
        AsyncMock(return_value=(None, None, version_id)),
    )
    run = SimpleNamespace(
        agent_version_id=uuid.uuid4() if case == "version_changed" else version_id
    )
    monkeypatch.setattr(
        api_runs.agent_run_repo,
        "get_run",
        AsyncMock(return_value=None if case == "run_gone" else run),
    )
    monkeypatch.setattr(
        api_runs.ConversationService,
        "check_api_conversation",
        AsyncMock(
            side_effect=NotFoundError(message="no access") if case == "lost_access" else None
        ),
    )
    inbox = SteeringInbox(
        poll=partial(ApiRunService._steering, parent, started),
        transcript={},
        screen=input_screen(GuardrailsConfig(blocked_keywords_in="salary", redact_secrets_in=True)),
    )
    deps = AgentDeps(run_id=uuid.uuid4(), steering=inbox)
    messages = [ModelRequest(parts=[UserPromptPart(content="go")])]
    ctx = MagicMock(deps=deps, messages=messages.copy())
    request = ModelRequestContext(
        model=TestModel(),
        messages=messages,
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
    )
    if case == "blocked":
        with pytest.raises(GuardrailBlocked):
            await Steering().before_model_request(ctx, request)
        finish.assert_not_awaited()
        assert ctx.messages == messages
        assert inbox.transcript == {}
    elif case == "redacted":
        sent = await Steering().before_model_request(ctx, request)
        assert "Added by the person" in str(sent.messages)
        assert text not in str(sent.messages) and text not in str(ctx.messages)
        assert inbox.transcript and text not in str(inbox.transcript)
        finish.assert_awaited_once_with(db, job_id=row.id, run_id=deps.run_id)
    else:
        assert await Steering().before_model_request(ctx, request) is request
        finish.assert_not_awaited()
    if case in {"lease_lost", "no_correction"}:
        context.assert_not_awaited()


async def test_an_insert_that_lost_the_race_answers_the_winners_request() -> None:
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="member")
    agent_id = uuid.uuid4()
    request = AgentRunRequest(prompt="summarise the week")
    conversation_id = uuid.uuid4()
    winner = MagicMock(
        id=uuid.uuid4(),
        kind=RUN_AGENT.kind,
        status="queued",
        created_at=datetime.now(UTC),
        finished_at=None,
        result=None,
        last_error=None,
        payload=RUN_AGENT.dump(
            RunAgent(
                agent_id=agent_id,
                organization_id=ctx.organization_id,
                user_id=ctx.subject_id,
                api_key_id=None,
                prompt=request.prompt,
                conversation_id=conversation_id,
                environment_id=None,
                file_ids=[],
                digest=digest(agent_id, request),
            )
        ),
    )

    @asynccontextmanager
    async def savepoint():
        yield

    db = MagicMock(begin_nested=savepoint)
    with (
        patch(
            "app.services.api_runs.ConversationService.for_api_run",
            new=AsyncMock(return_value=(conversation_id, None)),
        ),
        patch("app.services.api_runs.load_attached_files", new=AsyncMock(return_value=[])),
        patch(
            "app.services.api_runs.AgentRegistryService.get_runnable_spec",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.api_runs.enqueue",
            new=AsyncMock(side_effect=IntegrityError("INSERT", {}, Exception("duplicate key"))),
        ),
        patch(
            "app.services.api_runs.background_job_repo.get_by_idempotency_key",
            new=AsyncMock(side_effect=[None, winner]),
        ),
    ):
        answer = await ApiRunService(db).queue(ctx, agent_id, request, idempotency_key="order-7")

    assert (answer.id, answer.status, answer.conversation_id) == (
        winner.id,
        "queued",
        conversation_id,
    )


def _api_run_job(ctx: AuthContext, conversation_id: uuid.UUID) -> RunAgent:
    return RunAgent(
        agent_id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        user_id=ctx.subject_id,
        api_key_id=None,
        prompt="continue the discussion",
        conversation_id=conversation_id,
        environment_id=None,
        file_ids=[],
        digest="request-digest",
    )


def _run_row() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        status="succeeded",
        cost_usd=Decimal("0"),
        cost_is_partial=False,
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )


def _claim_with_lock(lock: asyncio.Lock, events: list[str]):
    @asynccontextmanager
    async def fake_claim(conversation_id: uuid.UUID, *, background: bool):
        assert background is False
        await lock.acquire()
        events.append("claim-enter")
        try:
            yield True
        finally:
            events.append("claim-exit")
            lock.release()

    return fake_claim


async def test_worker_claim_covers_api_room_recheck_and_run() -> None:
    """Conversion cannot commit between the saved-chat check and API turn write."""
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="member")
    conversation_id = uuid.uuid4()
    job = _api_run_job(ctx, conversation_id)
    lock = asyncio.Lock()
    events: list[str] = []
    shared_room = False
    run_started = asyncio.Event()
    conversion_waiting = asyncio.Event()
    finish_run = asyncio.Event()

    async def recheck(*args, **kwargs):
        assert lock.locked()
        assert not shared_room
        assert args[-1] == conversation_id
        assert kwargs["prompt"] == job.prompt
        events.append("recheck")
        return conversation_id, []

    async def load_files(*_args, **_kwargs):
        assert lock.locked()
        events.append("attachments")
        return []

    async def execute(*_args, **_kwargs):
        assert lock.locked()
        assert not shared_room
        events.append("execute")
        run_started.set()
        await finish_run.wait()
        events.append("execute-finished")
        return "answer", _run_row()

    async def parked(*_args, **_kwargs):
        assert lock.locked()
        events.append("parked")
        return []

    runner = MagicMock()
    runner.execute = AsyncMock(side_effect=execute)
    runner.parked_calls = AsyncMock(side_effect=parked)
    service = ApiRunService(MagicMock())
    service._context = AsyncMock(return_value=ctx)
    worker: asyncio.Task | None = None
    conversion: asyncio.Task | None = None

    try:
        with (
            patch("app.services.api_runs.claim", _claim_with_lock(lock, events)),
            patch(
                "app.services.api_runs.ConversationService.for_api_run",
                new=AsyncMock(side_effect=recheck),
            ),
            patch(
                "app.services.api_runs.load_attached_files",
                new=AsyncMock(side_effect=load_files),
            ),
            patch("app.services.api_runs.AgentRunnerService", return_value=runner),
        ):
            worker = asyncio.create_task(service.run(job))
            await asyncio.wait_for(run_started.wait(), timeout=1)

            async def convert_to_room() -> None:
                nonlocal shared_room
                conversion_waiting.set()
                async with lock:
                    shared_room = True
                    events.append("converted")

            conversion = asyncio.create_task(convert_to_room())
            await asyncio.wait_for(conversion_waiting.wait(), timeout=1)
            assert not shared_room, "the API turn must keep conversion out until it finishes"

            finish_run.set()
            result = await asyncio.wait_for(worker, timeout=1)
            await asyncio.wait_for(conversion, timeout=1)
    finally:
        finish_run.set()
        owned = [task for task in (worker, conversion) if task is not None]
        for task in owned:
            if not task.done():
                task.cancel()
        if owned:
            await asyncio.wait_for(asyncio.gather(*owned, return_exceptions=True), timeout=1)

    assert result.output == "answer"
    assert result.conversation_id == conversation_id
    assert events == [
        "claim-enter",
        "recheck",
        "attachments",
        "execute",
        "execute-finished",
        "parked",
        "claim-exit",
        "converted",
    ]


async def test_worker_refuses_a_chat_converted_before_its_claim() -> None:
    """The worker rechecks after admission, so a queued legacy run cannot enter a room."""
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="member")
    conversation_id = uuid.uuid4()
    job = _api_run_job(ctx, conversation_id)
    lock = asyncio.Lock()
    events: list[str] = []
    runner = MagicMock()
    runner.execute = AsyncMock()
    attachments = AsyncMock(return_value=[])

    async def recheck(*args, **_kwargs):
        assert lock.locked()
        assert args[-1] == conversation_id
        raise BadRequestError(
            message="Use the room composer and @mentions to message in a shared room"
        )

    service = ApiRunService(MagicMock())
    service._context = AsyncMock(return_value=ctx)
    with (
        patch("app.services.api_runs.claim", _claim_with_lock(lock, events)),
        patch(
            "app.services.api_runs.ConversationService.for_api_run",
            new=AsyncMock(side_effect=recheck),
        ),
        patch("app.services.api_runs.load_attached_files", attachments),
        patch("app.services.api_runs.AgentRunnerService", return_value=runner),
        pytest.raises(BadRequestError, match="room composer"),
    ):
        await service.run(job)

    assert events == ["claim-enter", "claim-exit"]
    assert not lock.locked()
    attachments.assert_not_awaited()
    runner.execute.assert_not_awaited()


async def test_worker_cancellation_releases_its_conversation_claim() -> None:
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="member")
    conversation_id = uuid.uuid4()
    job = _api_run_job(ctx, conversation_id)
    lock = asyncio.Lock()
    events: list[str] = []
    run_started = asyncio.Event()

    async def execute(*_args, **_kwargs):
        run_started.set()
        await asyncio.Event().wait()

    runner = MagicMock()
    runner.execute = AsyncMock(side_effect=execute)
    runner.parked_calls = AsyncMock(return_value=[])
    service = ApiRunService(MagicMock())
    service._context = AsyncMock(return_value=ctx)
    worker: asyncio.Task | None = None
    with (
        patch("app.services.api_runs.claim", _claim_with_lock(lock, events)),
        patch(
            "app.services.api_runs.ConversationService.for_api_run",
            new=AsyncMock(return_value=(conversation_id, [])),
        ),
        patch("app.services.api_runs.load_attached_files", new=AsyncMock(return_value=[])),
        patch("app.services.api_runs.AgentRunnerService", return_value=runner),
    ):
        worker = asyncio.create_task(service.run(job))
        try:
            await asyncio.wait_for(run_started.wait(), timeout=1)
            worker.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(worker, timeout=1)
        finally:
            if not worker.done():
                worker.cancel()
            await asyncio.wait_for(asyncio.gather(worker, return_exceptions=True), timeout=1)

    assert events == ["claim-enter", "claim-exit"]
    assert not lock.locked()
    runner.parked_calls.assert_not_awaited()


def test_ordinary_requests_keep_the_pre_steering_fingerprint() -> None:
    agent_id = uuid.UUID(int=1)
    request = AgentRunRequest(prompt="summarise the week")
    # Recorded from the original request schema and digest, before the opt-in existed.
    assert (
        digest(agent_id, request)
        == "a955d9dd2225745844a1103825300592fc123ddb9bfe235540943fdac4ab77d2"
    )


def test_explicit_executor_participates_in_idempotency_identity() -> None:
    agent_id = uuid.uuid4()
    ordinary = AgentRunRequest(prompt="make a report")
    own = ordinary.model_copy(update={"project_execution_target": "agent"})
    project = ordinary.model_copy(update={"project_execution_target": "project"})
    assert len({digest(agent_id, request) for request in (ordinary, own, project)}) == 3
    assert "project_execution_target" not in ordinary.model_dump(mode="json")
