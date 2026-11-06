"""A provider transfer remains bounded and cannot switch to an unconsented person."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import (
    AppException,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.services.telephony import runtime
from app.services.telephony.provider import AcceptanceUnknown
from tests.test_phone_authority import contact_and_call
from tests.test_telephony import AUTH, SID

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize(
    "change",
    [
        "ok",
        "agent",
        "missing",
        "no_caller",
        "wrong_run",
        "inactive",
        "rotated",
        "unlisted",
        "missing_contact",
        "expired",
        "refused",
        "unknown",
        "settled_during_transfer",
        "settled_during_refusal",
    ],
)
async def test_transfers_preserve_owner_consent_deadline_and_ambiguous_acceptance(
    monkeypatch, change
):
    contact, row, ctx = contact_and_call()
    row.status, row.provider_sid, row.voice_call_id = "active", SID, uuid4()
    row.endpoint_id, row.endpoint_generation = uuid4(), uuid4()
    row.created_at, row.cap_seconds = datetime.now(UTC), 120
    row.expires_at, row.stream_claimed_at = row.created_at + timedelta(seconds=120), None
    row.transferred_contact_id = None
    target_id, run_id = contact.id, uuid4()
    endpoint = MagicMock(generation=row.endpoint_generation, transfer_contact_ids=[str(target_id)])
    if change == "inactive":
        row.status = "ending"
    elif change == "rotated":
        endpoint.generation = uuid4()
    elif change == "unlisted":
        endpoint.transfer_contact_ids = []
    elif change in {"expired", "rotated", "transfer_removed", "expired_unavailable"}:
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db = AsyncMock()
    monkeypatch.setattr(runtime, "hold_subject", AsyncMock())
    monkeypatch.setattr(
        runtime.repo, "call", AsyncMock(return_value=None if change == "missing" else row)
    )
    monkeypatch.setattr(runtime.repo, "save", AsyncMock())
    monkeypatch.setattr(runtime.PhoneCallService, "readable", AsyncMock(return_value=row))
    monkeypatch.setattr(
        runtime.voice_call_repo,
        "get",
        AsyncMock(return_value=MagicMock(run_id=run_id) if change == "agent" else None),
    )
    monkeypatch.setattr(
        runtime.PhonePolicyService, "load_endpoint", AsyncMock(return_value=(endpoint, None, AUTH))
    )
    monkeypatch.setattr(
        runtime.repo,
        "contact_by_id",
        AsyncMock(return_value=None if change == "missing_contact" else contact),
    )
    monkeypatch.setattr(
        runtime.PhonePolicyService, "available_contact", AsyncMock(return_value=row.destination)
    )
    adapter = MagicMock(transfer=AsyncMock())
    if change == "refused":
        adapter.transfer.side_effect = BadRequestError(message="Provider refused")
    elif change == "unknown":
        adapter.transfer.side_effect = AcceptanceUnknown(message="Provider response lost")
    if change in {"settled_during_transfer", "settled_during_refusal"}:

        async def transferred(*args, **kwargs):
            row.status = "completed"
            if change == "settled_during_refusal":
                raise BadRequestError(message="Provider refused")

        adapter.transfer.side_effect = transferred
    args = {"ctx": ctx, "provider": adapter}
    if change == "agent":
        args = {"source_run_id": run_id, "endpoint_id": row.endpoint_id, "provider": adapter}
    if change in {"no_caller", "wrong_run"}:
        args = {"source_run_id": run_id if change == "wrong_run" else None, "provider": adapter}
    if change == "settled_during_transfer":
        await runtime.transfer(db, row.id, target_id, **args)
        assert row.status == "completed"
    elif change in {"ok", "agent"}:
        await runtime.transfer(db, row.id, target_id, **args)
        assert row.status == "transferred" and row.transferred_contact_id == contact.id
        assert 1 <= adapter.transfer.await_args.kwargs["seconds"] <= 120
    else:
        with pytest.raises(AppException):
            await runtime.transfer(db, row.id, target_id, **args)
        if change == "settled_during_refusal":
            assert row.status == "completed"
        elif change == "refused":
            assert row.status == "active" and row.transferred_contact_id is None
        elif change == "unknown":
            assert row.status == "transferring" and row.transferred_contact_id == contact.id
        else:
            adapter.transfer.assert_not_awaited()


@pytest.mark.parametrize(
    "change",
    [
        "ok",
        "agent",
        "missing",
        "no_caller",
        "wrong_run",
        "rotated",
        "inactive",
        "missing_target",
        "quiet",
        "deleted_person",
    ],
)
async def test_transfer_picker_shows_only_current_reachable_consenting_people(monkeypatch, change):
    from app.repositories import user_repo

    contact, row, ctx = contact_and_call()
    run_id = uuid4()
    row.status, row.voice_call_id, row.endpoint_id = "active", uuid4(), uuid4()
    row.endpoint_generation = uuid4()
    endpoint = MagicMock(generation=row.endpoint_generation, transfer_contact_ids=[str(contact.id)])
    if change == "rotated":
        endpoint.generation = uuid4()
    elif change == "inactive":
        row.status = "ending"
    monkeypatch.setattr(
        runtime.repo, "call", AsyncMock(return_value=None if change == "missing" else row)
    )
    monkeypatch.setattr(runtime.PhoneCallService, "readable", AsyncMock(return_value=row))
    monkeypatch.setattr(
        runtime.voice_call_repo,
        "get",
        AsyncMock(return_value=MagicMock(run_id=run_id) if change == "agent" else None),
    )
    monkeypatch.setattr(
        runtime.PhonePolicyService, "load_endpoint", AsyncMock(return_value=(endpoint, None, AUTH))
    )
    monkeypatch.setattr(
        runtime.repo,
        "contact_by_id",
        AsyncMock(return_value=None if change == "missing_target" else contact),
    )
    monkeypatch.setattr(
        runtime.PhonePolicyService,
        "available_contact",
        AsyncMock(
            side_effect=AuthorizationError(message="Quiet hours") if change == "quiet" else None
        ),
    )
    monkeypatch.setattr(
        user_repo,
        "get_by_id",
        AsyncMock(
            return_value=None if change == "deleted_person" else MagicMock(full_name="Case owner")
        ),
    )
    args = {"ctx": ctx}
    if change == "agent":
        args = {"source_run_id": run_id, "endpoint_id": row.endpoint_id}
    if change in {"no_caller", "wrong_run"}:
        args = {
            "source_run_id": uuid4() if change == "wrong_run" else None,
            "endpoint_id": row.endpoint_id,
        }
    if change in {"missing", "no_caller", "wrong_run"}:
        with pytest.raises((AuthorizationError, NotFoundError)):
            await runtime.transfer_options(AsyncMock(), row.id, **args)
    else:
        result = await runtime.transfer_options(AsyncMock(), row.id, **args)
        assert [choice.id for choice in result] == (
            [contact.id] if change in {"ok", "agent"} else []
        )


@pytest.mark.parametrize("status", ["queued", "active", "completed"])
async def test_hangup_cancels_queued_calls_without_claiming_they_connected(monkeypatch, status):
    _, row, ctx = contact_and_call()
    row.status = status
    db, ended = AsyncMock(), AsyncMock()
    monkeypatch.setattr(runtime.PhoneCallService, "readable", AsyncMock(return_value=row))
    monkeypatch.setattr(runtime.repo, "save", AsyncMock())
    monkeypatch.setattr(runtime, "end_media", ended)
    await runtime.hangup(db, ctx, row.id, provider=MagicMock())
    assert (
        row.status == {"queued": "cancelled", "active": "ending", "completed": "completed"}[status]
    )
    assert ended.await_count == (0 if status == "completed" else 1)
    if status == "queued":
        assert row.finished_at is not None and row.estimated_cost_usd == 0


@pytest.mark.parametrize(
    "change",
    [
        "live",
        "expired",
        "unavailable",
        "late_receipt",
        "no_sid",
        "settled_during_cleanup",
        "missing",
        "terminal",
        "rotated",
        "inbound",
        "transfer_removed",
        "transfer_live",
        "settled_before_cleanup",
        "expired_unavailable",
    ],
)
async def test_reaper_keeps_uncertain_reservations_until_the_hard_deadline(monkeypatch, change):
    _, row, _ = contact_and_call()
    now = datetime.now(UTC)
    row.status, row.direction = "active", "outbound"
    row.cap_seconds, row.created_at = 60, now
    row.stream_claimed_at, row.transferred_contact_id = None, None
    row.expires_at = (
        now - timedelta(seconds=1)
        if change in {"expired", "settled_during_cleanup", "expired_unavailable"}
        else now + timedelta(minutes=1)
    )
    row.provider_sid = None if change == "no_sid" else SID
    row.endpoint_id, row.endpoint_generation = uuid4(), uuid4()
    db = AsyncMock()

    @asynccontextmanager
    async def sessions():
        yield db

    monkeypatch.setattr(runtime.repo, "call", AsyncMock(return_value=row))
    monkeypatch.setattr(runtime.repo, "save", AsyncMock())
    monkeypatch.setattr(
        runtime.PhonePolicyService,
        "load_endpoint",
        AsyncMock(return_value=(MagicMock(generation=row.endpoint_generation), None, AUTH)),
    )
    monkeypatch.setattr(runtime, "live_contact", AsyncMock())
    if change == "missing":
        runtime.repo.call.return_value = None
    elif change == "terminal":
        row.status = "completed"
    elif change == "rotated":
        runtime.PhonePolicyService.load_endpoint.return_value[0].generation = uuid4()
    elif change == "inbound":
        row.direction = "inbound"
    elif change in {"transfer_removed", "transfer_live"}:
        row.transferred_contact_id = uuid4()
        monkeypatch.setattr(
            runtime.repo,
            "contact_by_id",
            AsyncMock(return_value=None if change == "transfer_removed" else MagicMock()),
        )
        monkeypatch.setattr(
            runtime.PhonePolicyService, "available_contact", AsyncMock(return_value=row.destination)
        )
    elif change == "settled_before_cleanup":
        row.expires_at = now - timedelta(seconds=1)
        runtime.repo.call.side_effect = [row, None]
    cleanup = AsyncMock(return_value=AUTH)
    monkeypatch.setattr(runtime, "_cleanup_credentials", cleanup)
    adapter = MagicMock(hangup=AsyncMock())
    if change in {"unavailable", "late_receipt", "no_sid"}:
        row.status = "ending"
    if change in {"unavailable", "expired_unavailable"}:
        cleanup.side_effect = AuthorizationError(message="Account removed")
    elif change == "late_receipt":
        adapter.hangup.side_effect = BadRequestError(message="Provider unreachable")
    elif change == "settled_during_cleanup":

        async def settle(*args):
            row.status = "completed"

        adapter.hangup.side_effect = settle
    result = await runtime._reap_one(row.id, provider=adapter, sessions=sessions)
    assert result is (change in {"expired", "rotated", "transfer_removed", "expired_unavailable"})
    if change in {"missing", "terminal", "settled_before_cleanup"}:
        adapter.hangup.assert_not_awaited()
    elif change in {"live", "inbound", "transfer_live"}:
        adapter.hangup.assert_not_awaited()
        assert row.status == "active"
    elif change in {"expired", "rotated", "transfer_removed", "expired_unavailable"}:
        assert row.status == "failed" and row.finished_at is not None
    elif change == "settled_during_cleanup":
        assert row.status == "completed"
    else:
        assert row.status == "ending"
