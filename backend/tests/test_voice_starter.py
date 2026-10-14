"""Every reason a call does not start, and what a started one leaves behind (#54)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.schemas.voice import StartFrame
from app.services.voice.exceptions import VoiceRefused
from app.services.voice.starter import VoiceCaller, VoiceCallStarter

pytestmark = pytest.mark.anyio
_M = "app.services.voice.starter"


class _World:
    """Everything the starter reads, as a happy path a test then breaks one piece of."""

    def __init__(self):
        self.org = SimpleNamespace(
            id=uuid4(),
            voice_conversations_enabled=True,
            voice_in_chat=True,
            voice_max_call_seconds=600,
            voice_monthly_minutes=600,
        )
        self.user_id = uuid4()
        self.agent = SimpleNamespace(
            id=uuid4(), organization_id=self.org.id, current_version_id=uuid4(), status="published"
        )
        self.conversation = SimpleNamespace(id=uuid4())
        self.headroom = Decimal("50")
        self.open_calls = 0
        self.previous = None

    def caller(self, **overrides) -> VoiceCaller:
        values = {
            "ctx": SimpleNamespace(
                organization_id=self.org.id, user_id=self.user_id, has=lambda p: True
            ),
            "user_id": self.user_id,
            "user_name": "Ann",
            "surface": "web",
            "anonymous": False,
            "auth_token": "t",
            "embed_id": None,
            "agent_id": self.agent.id,
            "conversation_id": None,
        }
        values.update(overrides)
        return VoiceCaller(**values)


@pytest.fixture
def world(monkeypatch):
    from app.agents.spec import AgentSpec, VoiceSpec

    w = _World()
    spec = AgentSpec(
        name="a", voice=VoiceSpec(provider="openai", model="gpt-realtime", secret_id=uuid4())
    )
    prepared = SimpleNamespace(
        run=SimpleNamespace(id=uuid4(), agent_version_id=None, conversation_id=w.conversation.id),
        built=SimpleNamespace(
            budget=SimpleNamespace(headroom=AsyncMock(side_effect=lambda: w.headroom)),
            ledger=MagicMock(),
        ),
        approvals=MagicMock(),
        spec=spec,
        agent=w.agent,
        realtime=MagicMock(),
    )
    monkeypatch.setattr(
        f"{_M}.organization_repo.get_by_id", AsyncMock(side_effect=lambda db, oid: w.org)
    )
    monkeypatch.setattr(
        f"{_M}.AgentRegistryService.get", AsyncMock(side_effect=lambda ctx, aid, perm: w.agent)
    )
    monkeypatch.setattr(f"{_M}.VoiceSettingsService.published_spec", AsyncMock(return_value=spec))
    monkeypatch.setattr(
        f"{_M}.VoiceSettingsService.minutes_left_seconds", AsyncMock(return_value=36_000)
    )
    monkeypatch.setattr(
        f"{_M}.conversation_repo.create_conversation", AsyncMock(return_value=w.conversation)
    )
    monkeypatch.setattr(
        f"{_M}.ConversationService.get_conversation", AsyncMock(return_value=w.conversation)
    )
    monkeypatch.setattr(
        f"{_M}.OrganizationSecretService.resolve_for_bindings",
        AsyncMock(side_effect=lambda ctx, ids: {ids[0]: MagicMock()}),
    )
    monkeypatch.setattr(f"{_M}.AgentRunnerService.prepare", AsyncMock(return_value=prepared))
    monkeypatch.setattr(
        f"{_M}.voice_call_repo.create", AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    )
    monkeypatch.setattr(
        f"{_M}.voice_call_repo.count_open_for_user",
        AsyncMock(side_effect=lambda db, **kw: w.open_calls),
    )
    monkeypatch.setattr(
        f"{_M}.voice_call_repo.get", AsyncMock(side_effect=lambda db, cid, **kw: w.previous)
    )
    monkeypatch.setattr(f"{_M}.voice_call_repo.chain_seconds", AsyncMock(return_value=0))
    monkeypatch.setattr(f"{_M}.voice_call_repo.end", AsyncMock())
    monkeypatch.setattr(f"{_M}.voice_call_repo.mark_hung_up", AsyncMock())
    monkeypatch.setattr(f"{_M}.hang_up_row", AsyncMock(return_value=True))
    monkeypatch.setattr(f"{_M}.agent_run_repo.close_voice_run", AsyncMock(return_value=True))
    monkeypatch.setattr(f"{_M}.agent_run_repo.expire_pending_approvals", AsyncMock(return_value=0))
    monkeypatch.setattr(f"{_M}.hold_subject", AsyncMock())
    monkeypatch.setattr(f"{_M}.build_realtime_model", MagicMock())
    w.prepared = prepared
    return w


def _starter():
    db = MagicMock(commit=AsyncMock(), rollback=AsyncMock(), refresh=AsyncMock())
    return VoiceCallStarter(db, sessions=MagicMock(), send=AsyncMock(), heard=lambda: None), db


async def test_a_started_call_is_committed_with_its_row_and_a_voice_run(world):
    starter, db = _starter()
    started = await starter.start(
        world.caller(),
        StartFrame(type="start", agent_id=world.agent.id, sdp_offer="v=0\r\nm=audio 9 x 111\r\n"),
    )
    db.commit.assert_awaited_once()
    assert started.cap_seconds == 600
    assert started.prepared is world.prepared


@pytest.mark.parametrize(
    ("breaks", "reason"),
    [
        (lambda w: setattr(w.org, "voice_conversations_enabled", False), "voice_off"),
        (lambda w: setattr(w.org, "voice_in_chat", False), "voice_off"),
        (lambda w: setattr(w, "headroom", Decimal("0.50")), "budget"),
        (lambda w: setattr(w, "open_calls", 1), "busy"),
    ],
)
async def test_each_refusal_rolls_back_and_names_its_reason(world, breaks, reason):
    breaks(world)
    starter, db = _starter()
    with pytest.raises(VoiceRefused) as refused:
        await starter.start(
            world.caller(),
            StartFrame(
                type="start", agent_id=world.agent.id, sdp_offer="v=0\r\nm=audio 9 x 111\r\n"
            ),
        )
    assert refused.value.reason == reason
    db.commit.assert_not_awaited()


async def test_a_model_the_price_snapshot_cannot_price_is_refused(world, monkeypatch):
    monkeypatch.setattr(f"{_M}.price_request", MagicMock(return_value=None))
    starter, _ = _starter()
    with pytest.raises(VoiceRefused) as refused:
        await starter.start(
            world.caller(),
            StartFrame(
                type="start", agent_id=world.agent.id, sdp_offer="v=0\r\nm=audio 9 x 111\r\n"
            ),
        )
    assert refused.value.reason == "not_priced"


async def test_someone_elses_conversation_cannot_be_called_into(world, monkeypatch):
    from app.core.exceptions import NotFoundError

    monkeypatch.setattr(
        f"{_M}.ConversationService.get_conversation",
        AsyncMock(side_effect=NotFoundError(message="x")),
    )
    starter, _ = _starter()
    with pytest.raises(VoiceRefused) as refused:
        await starter.start(
            world.caller(conversation_id=uuid4()),
            StartFrame(
                type="start",
                agent_id=world.agent.id,
                conversation_id=uuid4(),
                sdp_offer="v=0\r\nm=audio 9 x 111\r\n",
            ),
        )
    assert refused.value.reason == "forbidden"


async def test_resume_is_refused_for_another_conversation_or_after_ten_seconds(world):
    now = datetime.now(UTC)
    base = {
        "id": uuid4(),
        "user_id": world.user_id,
        "agent_id": world.agent.id,
        "conversation_id": world.conversation.id,
        "ended_at": now - timedelta(seconds=3),
    }
    frame = {
        "type": "start",
        "agent_id": world.agent.id,
        "conversation_id": world.conversation.id,
        "sdp_offer": "v=0\r\nm=audio 9 x 111\r\n",
    }

    for broken in (
        {"conversation_id": uuid4()},
        {"user_id": uuid4()},
        {"agent_id": uuid4()},
        {"ended_at": now - timedelta(seconds=11)},
    ):
        world.previous = SimpleNamespace(**{**base, **broken})
        starter, _ = _starter()
        with pytest.raises(VoiceRefused) as refused:
            await starter.start(
                world.caller(conversation_id=world.conversation.id),
                StartFrame(**frame, resume_of=world.previous.id),
            )
        assert refused.value.reason == "resume_refused"

    world.previous = SimpleNamespace(**base)
    starter, _ = _starter()
    started = await starter.start(
        world.caller(conversation_id=world.conversation.id),
        StartFrame(**frame, resume_of=base["id"]),
    )
    assert started.conversation_id == world.conversation.id


def _open_previous(world, **overrides):
    values = {
        "id": uuid4(),
        "organization_id": world.org.id,
        "user_id": world.user_id,
        "agent_id": world.agent.id,
        "conversation_id": world.conversation.id,
        "ended_at": None,
        "cost_usd": Decimal("0.10"),
        "seconds": 40,
        "guardrail_hits": 0,
        "transport": "webrtc",
        "provider": "openai",
        "provider_call_id": "rtc_0",
        "run_id": uuid4(),
        "secret_id": uuid4(),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _resume_frame(world, previous):
    return StartFrame(
        type="start",
        agent_id=world.agent.id,
        conversation_id=world.conversation.id,
        sdp_offer="v=0\r\nm=audio 9 x 111\r\n",
        resume_of=previous.id,
    )


async def test_resume_ends_a_connection_this_worker_still_holds_after_a_drop(world, monkeypatch):
    """A real network drop leaves the old socket half-open for 20-40 s; the one
    automatic retry arrives after 1.5 s and must not be refused (review B1)."""
    from app.db.models.voice_call import VoiceEndReason
    from app.services.voice.registry import LIVE_CALLS

    previous = _open_previous(world)
    ended = SimpleNamespace(**{**previous.__dict__, "ended_at": datetime.now(UTC)})
    monkeypatch.setattr(f"{_M}.voice_call_repo.get", AsyncMock(side_effect=[previous, ended]))
    held = MagicMock(closed=AsyncMock())
    LIVE_CALLS.add(held)
    LIVE_CALLS.bind(previous.id, held)
    try:
        starter, _ = _starter()
        started = await starter.start(
            world.caller(conversation_id=world.conversation.id), _resume_frame(world, previous)
        )
    finally:
        LIVE_CALLS.discard(held)
    held.request_end.assert_called_once_with(VoiceEndReason.DISCONNECTED)
    assert started.conversation_id == world.conversation.id


async def test_resume_ends_and_hangs_up_a_connection_another_worker_holds(world, monkeypatch):
    previous = _open_previous(world)
    ended = SimpleNamespace(**{**previous.__dict__, "ended_at": datetime.now(UTC)})
    monkeypatch.setattr(f"{_M}.voice_call_repo.get", AsyncMock(side_effect=[previous, ended]))
    starter, _ = _starter()

    await starter.start(
        world.caller(conversation_id=world.conversation.id), _resume_frame(world, previous)
    )

    from app.services.voice import starter as starter_module

    assert starter_module.voice_call_repo.end.await_args.kwargs["reason"].value == "disconnected"
    assert starter_module.hang_up_row.await_args.args[1] is previous
    starter_module.voice_call_repo.mark_hung_up.assert_awaited_once()


async def test_resume_is_refused_when_the_old_connection_will_not_end(world, monkeypatch):
    previous = _open_previous(world)
    monkeypatch.setattr(f"{_M}.voice_call_repo.get", AsyncMock(return_value=previous))
    monkeypatch.setattr(f"{_M}.limits.RESUME_WAIT_SECONDS", 0.05)
    starter, db = _starter()
    with pytest.raises(VoiceRefused) as refused:
        await starter.start(
            world.caller(conversation_id=world.conversation.id), _resume_frame(world, previous)
        )
    assert refused.value.reason == "resume_refused"
    db.commit.assert_not_awaited()


async def test_a_key_that_cannot_build_a_model_is_refused_before_the_commit(world, monkeypatch):
    from app.core.exceptions import BadRequestError

    monkeypatch.setattr(
        f"{_M}.build_realtime_model", MagicMock(side_effect=BadRequestError(message="wrong kind"))
    )
    starter, db = _starter()
    with pytest.raises(VoiceRefused) as refused:
        await starter.start(
            world.caller(),
            StartFrame(
                type="start", agent_id=world.agent.id, sdp_offer="v=0\r\nm=audio 9 x 111\r\n"
            ),
        )
    assert refused.value.reason == "not_configured"
    db.commit.assert_not_awaited()


async def test_a_webrtc_offer_with_a_data_channel_is_refused_before_anything_is_written(world):
    starter, db = _starter()
    with pytest.raises(VoiceRefused) as refused:
        await starter.start(
            world.caller(),
            StartFrame(
                type="start",
                agent_id=world.agent.id,
                sdp_offer="v=0\r\nm=audio 9 x 111\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n",
            ),
        )
    assert refused.value.reason == "data_channel"
    db.commit.assert_not_awaited()


_OFFER = "v=0\r\nm=audio 9 x 111\r\n"


async def _refusal(world, *, caller=None, frame=None) -> str:
    starter, db = _starter()
    with pytest.raises(VoiceRefused) as refused:
        await starter.start(
            caller or world.caller(),
            frame or StartFrame(type="start", agent_id=world.agent.id, sdp_offer=_OFFER),
        )
    db.commit.assert_not_awaited()
    db.rollback.assert_awaited()
    return refused.value.reason


async def test_a_call_names_an_agent(world):
    assert (
        await _refusal(world, caller=world.caller(agent_id=None), frame=StartFrame(type="start"))
        == "no_agent"
    )


async def test_an_agent_the_caller_may_not_run_cannot_be_called(world, monkeypatch):
    from app.core.exceptions import NotFoundError

    monkeypatch.setattr(
        f"{_M}.AgentRegistryService.get", AsyncMock(side_effect=NotFoundError(message="x"))
    )
    assert await _refusal(world) == "forbidden"


async def test_an_agent_without_a_voice_section_is_not_set_up_for_calls(world, monkeypatch):
    from app.agents.spec import AgentSpec

    monkeypatch.setattr(
        f"{_M}.VoiceSettingsService.published_spec", AsyncMock(return_value=AgentSpec(name="a"))
    )
    assert await _refusal(world) == "not_configured"


async def test_a_webrtc_call_needs_an_offer(world):
    assert (
        await _refusal(world, frame=StartFrame(type="start", agent_id=world.agent.id))
        == "bad_offer"
    )


async def test_a_month_with_less_than_a_minute_left_is_refused(world, monkeypatch):
    monkeypatch.setattr(
        f"{_M}.VoiceSettingsService.minutes_left_seconds", AsyncMock(return_value=30)
    )
    assert await _refusal(world) == "minutes_exhausted"


async def test_a_voice_key_deleted_since_publish_is_refused(world, monkeypatch):
    monkeypatch.setattr(
        f"{_M}.OrganizationSecretService.resolve_for_bindings", AsyncMock(return_value={})
    )
    assert await _refusal(world) == "not_configured"


async def test_an_anonymous_visitor_is_not_counted_against_a_person(world, monkeypatch):
    claimed = AsyncMock()
    monkeypatch.setattr(f"{_M}.VoiceCallStarter._claim_slot", claimed)
    starter, db = _starter()

    await starter.start(
        world.caller(user_id=None, anonymous=True, surface="embed", embed_id=uuid4()),
        StartFrame(type="start", agent_id=world.agent.id, sdp_offer=_OFFER),
    )

    claimed.assert_not_awaited()
    db.commit.assert_awaited_once()


async def test_a_previous_connection_whose_hang_up_failed_is_left_for_the_reaper(
    world, monkeypatch
):
    previous = _open_previous(world)
    ended = SimpleNamespace(**{**previous.__dict__, "ended_at": datetime.now(UTC)})
    monkeypatch.setattr(f"{_M}.voice_call_repo.get", AsyncMock(side_effect=[previous, ended]))
    monkeypatch.setattr(f"{_M}.hang_up_row", AsyncMock(return_value=False))
    marked = AsyncMock()
    monkeypatch.setattr(f"{_M}.voice_call_repo.mark_hung_up", marked)
    starter, _ = _starter()

    await starter.start(
        world.caller(conversation_id=world.conversation.id), _resume_frame(world, previous)
    )

    marked.assert_not_awaited()


async def test_a_relay_call_needs_no_offer_and_a_per_minute_model_no_token_price(
    world, monkeypatch
):
    from app.agents.spec import AgentSpec, VoiceSpec

    spec = AgentSpec(
        name="a", voice=VoiceSpec(provider="xai", model="grok-voice-latest", secret_id=uuid4())
    )
    monkeypatch.setattr(f"{_M}.VoiceSettingsService.published_spec", AsyncMock(return_value=spec))
    priced = MagicMock(return_value=None)
    monkeypatch.setattr(f"{_M}.price_request", priced)
    starter, db = _starter()

    started = await starter.start(world.caller(), StartFrame(type="start", agent_id=world.agent.id))

    assert started.resolved.entry.transport == "relay"
    priced.assert_not_called()
    db.commit.assert_awaited_once()


async def test_an_azure_call_is_metered_at_its_base_models_price(world, monkeypatch):
    """The deployment's name prices nothing; the base model on OpenAI's list does. Fakes only."""
    from pydantic_ai.usage import RunUsage

    from app.agents.capabilities.budget import SpendLedger
    from app.agents.spec import AgentSpec, VoiceSpec

    spec = AgentSpec(
        name="a",
        voice=VoiceSpec(
            provider="azure", deployment="rt-prod", base_model="gpt-realtime", secret_id=uuid4()
        ),
    )
    monkeypatch.setattr(f"{_M}.VoiceSettingsService.published_spec", AsyncMock(return_value=spec))
    world.prepared.built.ledger = SpendLedger()
    starter, _ = _starter()

    started = await starter.start(world.caller(), StartFrame(type="start", agent_id=world.agent.id))
    usage = RunUsage(input_tokens=1000, output_tokens=1000)
    started.meter.book_response(usage)

    assert started.resolved.wire_model == "rt-prod"
    assert started.meter.total_usd > 0
    assert usage.cost == started.meter.total_usd


async def test_a_connection_taken_over_on_a_dead_worker_closes_its_run_as_continued(
    world, monkeypatch
):
    previous = _open_previous(world)
    ended = SimpleNamespace(**{**previous.__dict__, "ended_at": datetime.now(UTC)})
    monkeypatch.setattr(f"{_M}.voice_call_repo.get", AsyncMock(side_effect=[previous, ended]))
    closed = AsyncMock(return_value=True)
    expired = AsyncMock(return_value=0)
    monkeypatch.setattr(f"{_M}.agent_run_repo.close_voice_run", closed)
    monkeypatch.setattr(f"{_M}.agent_run_repo.expire_pending_approvals", expired)
    starter, _ = _starter()

    await starter.start(
        world.caller(conversation_id=world.conversation.id), _resume_frame(world, previous)
    )

    assert closed.await_args.kwargs["run_id"] == previous.run_id
    assert closed.await_args.kwargs["status"] == "cancelled"
    assert expired.await_args.kwargs["run_id"] == previous.run_id


async def test_a_taken_over_connection_ended_long_ago_by_the_takeover_still_resumes(
    world, monkeypatch
):
    """The ten-second window is for a connection that ended on its own; one this
    reconnect ended (after waiting for its hang-up) ended for the reconnect."""
    previous = _open_previous(world)
    ended = SimpleNamespace(
        **{**previous.__dict__, "ended_at": datetime.now(UTC) - timedelta(seconds=25)}
    )
    monkeypatch.setattr(f"{_M}.voice_call_repo.get", AsyncMock(side_effect=[previous, ended]))
    starter, _ = _starter()

    started = await starter.start(
        world.caller(conversation_id=world.conversation.id), _resume_frame(world, previous)
    )

    assert started.conversation_id == world.conversation.id


async def test_a_reconnect_with_its_calls_time_used_up_is_refused_for_time_not_minutes(
    world, monkeypatch
):
    world.previous = SimpleNamespace(
        id=uuid4(),
        user_id=world.user_id,
        agent_id=world.agent.id,
        conversation_id=world.conversation.id,
        ended_at=datetime.now(UTC) - timedelta(seconds=3),
    )
    monkeypatch.setattr(f"{_M}.voice_call_repo.chain_seconds", AsyncMock(return_value=580))
    starter, _ = _starter()
    with pytest.raises(VoiceRefused) as refused:
        await starter.start(
            world.caller(conversation_id=world.conversation.id),
            StartFrame(
                type="start",
                agent_id=world.agent.id,
                conversation_id=world.conversation.id,
                sdp_offer="v=0\r\nm=audio 9 x 111\r\n",
                resume_of=world.previous.id,
            ),
        )
    assert refused.value.reason == "call_limit"


async def test_a_taken_over_connection_whose_run_was_deleted_is_still_ended(world, monkeypatch):
    previous = _open_previous(world, run_id=None)
    ended = SimpleNamespace(**{**previous.__dict__, "ended_at": datetime.now(UTC)})
    monkeypatch.setattr(f"{_M}.voice_call_repo.get", AsyncMock(side_effect=[previous, ended]))
    closed = AsyncMock(return_value=True)
    monkeypatch.setattr(f"{_M}.agent_run_repo.close_voice_run", closed)
    starter, _ = _starter()

    await starter.start(
        world.caller(conversation_id=world.conversation.id), _resume_frame(world, previous)
    )

    closed.assert_not_awaited()
