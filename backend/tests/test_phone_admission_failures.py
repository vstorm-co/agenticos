"""Refusals stop a telephone intention before allocating provider work."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError, BadRequestError, ConflictError
from app.schemas.telephony import PhoneCallCreate
from app.services.telephony import calls, cases
from tests.test_phone_authority import contact_and_call

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize("reason", ["consent", "missing", "closed", "run", "owner", "notification"])
async def test_important_contact_requires_a_live_owned_unacknowledged_case(monkeypatch, reason):
    contact, row, ctx = contact_and_call()
    agent_id, outcome_id, conversation_id, run_id = uuid4(), uuid4(), uuid4(), uuid4()
    contact.allow_important = reason != "consent"
    contact.agent_ids = [str(agent_id)]
    contact.escalation_delay_seconds = 30
    outcome = MagicMock(status="open", source_run_id=run_id, source_conversation_id=conversation_id)
    if reason == "closed":
        outcome.status = "done"
    source = MagicMock(agent_id=agent_id, user_id=uuid4() if reason == "owner" else ctx.user_id)
    monkeypatch.setattr(
        cases.repo, "own_case", AsyncMock(return_value=None if reason == "missing" else outcome)
    )
    monkeypatch.setattr(
        cases.agent_run_repo, "get_run", AsyncMock(return_value=None if reason == "run" else source)
    )
    monkeypatch.setattr(cases.AgentRegistryService, "get", AsyncMock())
    monkeypatch.setattr(cases.ConversationService, "get_conversation", AsyncMock())
    monkeypatch.setattr(cases.repo, "case_notification_time", AsyncMock(return_value=None))
    with pytest.raises(AuthorizationError):
        await cases.eligible_case(
            AsyncMock(),
            ctx,
            contact,
            outcome_id=outcome_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
        )


@pytest.mark.parametrize(
    "reason",
    [
        "anonymous",
        "missing_contact",
        "no_published",
        "no_agent_case",
        "settled_case",
        "missing_run",
        "test_run",
        "key_run",
        "unselected_agent",
        "other_agent",
        "scheduled_interactive",
        "unpublished",
        "no_voice",
    ],
)
async def test_call_admission_refuses_unconsented_or_unpublished_execution(monkeypatch, reason):
    contact, row, ctx = contact_and_call()
    if reason == "anonymous":
        from dataclasses import replace

        ctx = replace(ctx, user_id=None)
    agent_id, endpoint_id, version_id, source_id = uuid4(), uuid4(), uuid4(), uuid4()
    contact.agent_ids = [] if reason == "unselected_agent" else [str(agent_id)]
    run = MagicMock(
        user_id=ctx.user_id,
        is_test=False,
        key_scopes=None,
        initiated_by_publisher_fallback=False,
        agent_id=agent_id,
        routine_origin_id=None,
        agent_version_id=version_id,
    )
    if reason == "test_run":
        run.is_test = True
    elif reason == "key_run":
        run.key_scopes = []
    elif reason == "other_agent":
        run.agent_id = uuid4()
        contact.agent_ids = [str(run.agent_id)]
    elif reason == "scheduled_interactive":
        run.routine_origin_id = uuid4()
    elif reason == "unpublished":
        run.agent_version_id = None
    monkeypatch.setattr(calls, "hold_subject", AsyncMock())
    monkeypatch.setattr(calls.repo, "call_for_source", AsyncMock(return_value=None))
    monkeypatch.setattr(calls.repo, "request", AsyncMock(return_value=None))
    monkeypatch.setattr(
        calls.repo,
        "contact",
        AsyncMock(return_value=None if reason == "missing_contact" else contact),
    )
    monkeypatch.setattr(
        calls.PhonePolicyService,
        "load_endpoint",
        AsyncMock(return_value=(MagicMock(), None, MagicMock())),
    )
    monkeypatch.setattr(
        calls.PhonePolicyService, "available_contact", AsyncMock(return_value=row.destination)
    )
    monkeypatch.setattr(
        calls.AgentRegistryService,
        "get",
        AsyncMock(
            return_value=MagicMock(
                current_version_id=None if reason == "no_published" else version_id
            )
        ),
    )
    monkeypatch.setattr(
        calls.AgentRegistryService,
        "get_pinned_spec",
        AsyncMock(return_value=(None, MagicMock(voice=None), None)),
    )
    monkeypatch.setattr(
        calls.agent_run_repo,
        "get_run",
        AsyncMock(return_value=None if reason == "missing_run" else run),
    )
    budget = AsyncMock()
    monkeypatch.setattr(calls.PhonePolicyService, "admit_budget", budget)
    data = PhoneCallCreate(
        endpoint_id=endpoint_id,
        request_key=uuid4(),
        mode="conversation"
        if reason in {"scheduled_interactive", "unpublished", "no_voice", "no_published"}
        else "report",
        report=None
        if reason in {"scheduled_interactive", "unpublished", "no_voice", "no_published"}
        else "A report",
        agent_id=None if reason == "no_agent_case" else agent_id,
        outcome_id=uuid4() if reason in {"no_agent_case", "settled_case"} else None,
        importance_reason="Important" if reason in {"no_agent_case", "settled_case"} else None,
    )
    monkeypatch.setattr(calls.repo, "call_for_case", AsyncMock(return_value=None))
    monkeypatch.setattr(cases, "eligible_case", AsyncMock(return_value=datetime.now(UTC)))
    monkeypatch.setattr(calls.repo, "mark_case_phone_attempt", AsyncMock(return_value=False))
    with pytest.raises((AuthorizationError, BadRequestError, ConflictError)):
        await calls.PhoneCallService(AsyncMock()).create(
            ctx,
            data,
            source_run_id=None
            if reason in {"no_published", "no_agent_case", "settled_case"}
            else source_id,
        )
    assert budget.await_count == int(reason == "settled_case")


@pytest.mark.parametrize(
    "reason", ["account", "number", "disabled", "receipt", "ended", "rotated", "expired", "current"]
)
async def test_inbound_admission_refuses_wrong_endpoint_and_finished_receipts(monkeypatch, reason):
    from tests.test_telephony import AUTH, SID

    _, row, _ = contact_and_call()
    endpoint = MagicMock(
        id=uuid4(), organization_id=uuid4(), inbound_embed_id=uuid4(), generation=uuid4()
    )
    row.status, row.endpoint_generation, row.expires_at = (
        "active",
        endpoint.generation,
        datetime.now(UTC) + timedelta(minutes=1),
    )
    params = {"AccountSid": AUTH.account, "To": AUTH.number, "CallSid": SID}
    if reason == "account":
        params["AccountSid"] = "wrong"
    elif reason == "number":
        params["To"] = "+15550000000"
    elif reason == "disabled":
        endpoint.inbound_embed_id = None
    elif reason == "receipt":
        params["CallSid"] = "invalid"
    elif reason == "ended":
        row.status = "completed"
    elif reason == "rotated":
        row.endpoint_generation = uuid4()
    elif reason == "expired":
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    monkeypatch.setattr(calls, "hold_subject", AsyncMock())
    monkeypatch.setattr(
        calls.PhonePolicyService, "load_endpoint", AsyncMock(return_value=(endpoint, None, AUTH))
    )
    monkeypatch.setattr(calls.repo, "request", AsyncMock(return_value=row))
    budget = AsyncMock()
    monkeypatch.setattr(calls.PhonePolicyService, "admit_budget", budget)
    if reason == "current":
        assert await calls.PhoneCallService(AsyncMock()).inbound(endpoint.id, params) is row
    else:
        with pytest.raises((AuthorizationError, ConflictError)):
            await calls.PhoneCallService(AsyncMock()).inbound(endpoint.id, params)
    budget.assert_not_awaited()


async def test_an_authenticated_inbound_call_hangs_up_if_provider_cap_is_unconfirmed(monkeypatch):
    from app.core.config import settings
    from app.services.telephony import webhooks

    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://phone.example")
    from tests.test_telephony import AUTH

    _, row, _ = contact_and_call()
    monkeypatch.setattr(
        webhooks.PhonePolicyService,
        "load_endpoint",
        AsyncMock(return_value=(MagicMock(), None, AUTH)),
    )
    monkeypatch.setattr(webhooks, "signature_ok", lambda *args: True)
    monkeypatch.setattr(webhooks.PhoneCallService, "inbound", AsyncMock(return_value=row))
    monkeypatch.setattr(
        webhooks,
        "cap_inbound",
        AsyncMock(side_effect=BadRequestError(message="Cannot confirm cap")),
    )
    assert (
        await webhooks.PhoneWebhookService(AsyncMock()).inbound(
            uuid4(), b"CallSid=receipt", "signed"
        )
        == "<Response><Hangup /></Response>"
    )


@pytest.mark.parametrize("delayed", [False, True])
async def test_important_case_escalation_time_comes_from_the_owners_notification(
    monkeypatch, delayed
):
    contact, _, ctx = contact_and_call()
    agent_id, outcome_id, conversation_id = uuid4(), uuid4(), uuid4()
    contact.allow_important, contact.agent_ids = True, [str(agent_id)]
    contact.escalation_delay_seconds = 120 if delayed else 0
    notified = datetime.now(UTC) - timedelta(minutes=1)
    monkeypatch.setattr(
        cases.repo,
        "own_case",
        AsyncMock(
            return_value=MagicMock(
                status="open", source_run_id=uuid4(), source_conversation_id=conversation_id
            )
        ),
    )
    monkeypatch.setattr(
        cases.agent_run_repo,
        "get_run",
        AsyncMock(return_value=MagicMock(agent_id=agent_id, user_id=ctx.user_id)),
    )
    monkeypatch.setattr(cases.AgentRegistryService, "get", AsyncMock())
    monkeypatch.setattr(cases.ConversationService, "get_conversation", AsyncMock())
    monkeypatch.setattr(cases.repo, "case_notification_time", AsyncMock(return_value=notified))
    before = datetime.now(UTC)
    result = await cases.eligible_case(
        AsyncMock(),
        ctx,
        contact,
        outcome_id=outcome_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
    )
    if delayed:
        assert result == notified + timedelta(seconds=120)
    else:
        assert before <= result <= datetime.now(UTC)
