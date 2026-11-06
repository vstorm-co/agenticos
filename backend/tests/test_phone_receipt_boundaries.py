"""Late provider receipts cannot revive calls or discard unconfirmed reservations."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.exceptions import AuthorizationError, NotFoundError
from app.services.telephony import runtime
from tests.test_phone_authority import contact_and_call
from tests.test_telephony import AUTH, SID

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "inbound_destination",
        "terminal",
        "ringing",
        "duration_invalid",
        "duration_long",
        "transferred",
    ],
)
async def test_status_callbacks_preserve_terminal_state_and_conservative_cost(monkeypatch, change):
    _, row, _ = contact_and_call()
    row.status, row.direction, row.account_sid = "completed", "inbound", AUTH.account
    row.provider_sid, row.transferred_contact_id = SID, None
    row.cap_seconds, row.estimated_cost_usd, row.price_per_minute_usd = (
        120,
        Decimal("0.2"),
        Decimal("0.1"),
    )
    params = {
        "AccountSid": AUTH.account,
        "To": AUTH.number,
        "CallSid": SID,
        "CallStatus": "completed",
        "CallDuration": "30",
    }
    if change == "ringing":
        row.status = "ringing"
        params["CallStatus"] = "ringing"
    if change == "inbound_destination":
        params["To"] = "+15550000001"
    elif change == "terminal":
        params["CallStatus"] = "ringing"
    elif change == "duration_invalid":
        params["CallDuration"] = "unknown"
    elif change == "duration_long":
        params["CallDuration"] = "1000000"
    elif change == "transferred":
        row.transferred_contact_id = uuid4()
    monkeypatch.setattr(
        runtime.repo, "call", AsyncMock(return_value=None if change == "missing" else row)
    )
    monkeypatch.setattr(runtime, "_cleanup_credentials", AsyncMock(return_value=AUTH))
    saved = AsyncMock()
    monkeypatch.setattr(runtime.repo, "save", saved)
    if change in {"missing", "inbound_destination"}:
        with pytest.raises((NotFoundError, AuthorizationError)):
            await runtime.status_callback(AsyncMock(), row.id, params)
        saved.assert_not_awaited()
    else:
        await runtime.status_callback(AsyncMock(), row.id, params)
        assert row.status == (
            "ringing" if change == "ringing" else "completed"
        ) and row.estimated_cost_usd == Decimal("0.2")
        assert saved.await_count == (0 if change == "terminal" else 1)


@pytest.mark.parametrize(
    "change", ["endpoint_removed", "bot_removed", "bot_rotated", "account_changed"]
)
async def test_cleanup_cannot_use_another_telephone_account(monkeypatch, change):
    _, row, _ = contact_and_call()
    row.endpoint_id, row.account_sid = uuid4(), AUTH.account
    generation = uuid4()
    endpoint = MagicMock(bot_generation=generation)
    bot = MagicMock(authorization_generation=uuid4() if change == "bot_rotated" else generation)
    monkeypatch.setattr(
        runtime.repo,
        "endpoint",
        AsyncMock(return_value=None if change == "endpoint_removed" else endpoint),
    )
    from app.repositories import channel_bot_repo

    monkeypatch.setattr(
        channel_bot_repo,
        "get_for_org",
        AsyncMock(return_value=None if change == "bot_removed" else bot),
    )
    from app.services.telephony import provider

    monkeypatch.setattr(provider, "credentials", lambda _bot: AUTH)
    if change == "account_changed":
        row.account_sid = "another"
    with pytest.raises((NotFoundError, AuthorizationError)):
        await runtime._cleanup_credentials(AsyncMock(), row)


@pytest.mark.parametrize("change", ["terminal", "removed_after_hangup", "settled_after_hangup"])
async def test_media_cleanup_never_overwrites_a_later_terminal_receipt(monkeypatch, change):
    _, row, _ = contact_and_call()
    row.status, row.provider_sid = ("completed" if change == "terminal" else "active"), SID
    db = AsyncMock()

    @asynccontextmanager
    async def sessions():
        yield db

    read = AsyncMock(side_effect=[row, None if change == "removed_after_hangup" else row])
    monkeypatch.setattr(runtime.repo, "call", read)
    monkeypatch.setattr(runtime.repo, "save", AsyncMock())
    monkeypatch.setattr(runtime, "_cleanup_credentials", AsyncMock(return_value=AUTH))

    async def hangup(*args):
        if change == "settled_after_hangup":
            row.status = "completed"

    provider = MagicMock(hangup=AsyncMock(side_effect=hangup))
    await runtime.end_media(row.id, provider=provider, sessions=sessions)
    if change == "terminal":
        provider.hangup.assert_not_awaited()
    else:
        provider.hangup.assert_awaited_once()
        assert runtime.repo.save.await_count == 1


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "terminal",
        "claimed",
        "rotated",
        "expired",
        "ending",
        "sid",
        "inbound_disabled",
        "inbound_removed",
    ],
)
async def test_stream_claim_rejects_stale_or_unauthorized_receipts(monkeypatch, change):
    _, row, _ = contact_and_call()
    row.status, row.direction = "active", "inbound"
    row.provider_sid, row.stream_claimed_at = SID, None
    row.endpoint_generation, row.endpoint_id = uuid4(), uuid4()
    row.expires_at, row.cap_seconds = datetime.now(UTC) + timedelta(seconds=60), 60
    endpoint = MagicMock(generation=row.endpoint_generation, inbound_embed_id=uuid4())
    if change == "terminal":
        row.status = "completed"
    elif change == "claimed":
        row.stream_claimed_at = datetime.now(UTC)
    elif change == "rotated":
        endpoint.generation = uuid4()
    elif change == "expired":
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    elif change == "ending":
        row.status = "ending"
    elif change == "sid":
        row.provider_sid = "another"
    elif change == "inbound_disabled":
        endpoint.inbound_embed_id = None
    db = AsyncMock()

    @asynccontextmanager
    async def sessions():
        yield db

    monkeypatch.setattr(runtime, "hold_subject", AsyncMock())
    monkeypatch.setattr(
        runtime.repo, "call", AsyncMock(return_value=None if change == "missing" else row)
    )
    monkeypatch.setattr(
        runtime.PhonePolicyService, "load_endpoint", AsyncMock(return_value=(endpoint, None, AUTH))
    )
    monkeypatch.setattr(runtime.agent_embed_repo, "get", AsyncMock(return_value=None))
    with pytest.raises(WebSocketDisconnect):
        await runtime._claim_stream(row.id, sessions, provider_sid=SID)
    db.commit.assert_not_awaited()


async def test_removed_dial_intentions_never_call_the_provider(monkeypatch):
    db = AsyncMock()

    @asynccontextmanager
    async def sessions():
        yield db

    monkeypatch.setattr(runtime.repo, "call", AsyncMock(return_value=None))
    provider = MagicMock(dial=AsyncMock())
    await runtime.dial(uuid4(), provider=provider, sessions=sessions)
    provider.dial.assert_not_awaited()


@pytest.mark.parametrize("source", ["none", "private", "project", "another_owner"])
@pytest.mark.parametrize("case_present", [False, True])
async def test_outbound_voice_inherits_only_its_owners_private_context(
    monkeypatch, source, case_present
):
    _, row, ctx = contact_and_call()
    row.status, row.direction, row.mode = "ringing", "outbound", "conversation"
    row.stream_claimed_at, row.provider_sid = None, SID
    row.endpoint_generation, row.endpoint_id = uuid4(), uuid4()
    row.expires_at, row.cap_seconds = datetime.now(UTC) + timedelta(seconds=60), 60
    row.source_conversation_id = None if source == "none" else uuid4()
    row.outcome_id, row.importance_reason = uuid4(), "Review required"
    row.agent_id, row.agent_version_id = uuid4(), uuid4()
    case = MagicMock(id=row.outcome_id, summary="A case")
    conversation = MagicMock(
        id=row.source_conversation_id,
        project_id=uuid4() if source == "project" else None,
        user_id=uuid4() if source == "another_owner" else row.user_id,
    )
    db = AsyncMock()

    @asynccontextmanager
    async def sessions():
        yield db

    monkeypatch.setattr(runtime, "hold_subject", AsyncMock())
    monkeypatch.setattr(runtime.repo, "call", AsyncMock(return_value=row))
    monkeypatch.setattr(runtime.repo, "save", AsyncMock())
    monkeypatch.setattr(
        runtime.repo, "own_case", AsyncMock(return_value=case if case_present else None)
    )
    monkeypatch.setattr(runtime, "live_contact", AsyncMock(return_value=ctx))
    monkeypatch.setattr(
        runtime.ConversationService, "get_conversation", AsyncMock(return_value=conversation)
    )
    monkeypatch.setattr(
        runtime.PhonePolicyService,
        "load_endpoint",
        AsyncMock(return_value=(MagicMock(generation=row.endpoint_generation), None, AUTH)),
    )
    caller = await runtime._claim_stream(row.id, sessions, provider_sid=SID)
    assert caller.conversation_id == (row.source_conversation_id if source == "private" else None)
    assert (caller.phone_context is not None) is case_present
    assert row.stream_claimed_at is not None


async def test_inbound_cap_refuses_an_expired_original_deadline(monkeypatch):
    from app.core.exceptions import ConflictError

    _, row, _ = contact_and_call()
    row.provider_sid, row.cap_seconds = SID, 60
    row.created_at = datetime.now(UTC) - timedelta(minutes=2)
    monkeypatch.setattr(
        runtime.PhonePolicyService,
        "load_endpoint",
        AsyncMock(return_value=(MagicMock(), None, AUTH)),
    )
    provider = MagicMock(cap=AsyncMock())
    with pytest.raises(ConflictError, match="original deadline"):
        await runtime.cap_inbound(AsyncMock(), row, provider=provider)
    provider.cap.assert_not_awaited()
