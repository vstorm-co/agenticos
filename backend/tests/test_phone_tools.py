"""Telephone tools retain the admitted person and live-call ownership on every path."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from app.agents.capabilities.phone_calls import _toolset
from app.agents.capabilities.phone_calls._toolset import PhoneCallTools
from app.agents.deps import AgentDeps
from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext
from app.repositories import telephony as repo
from app.schemas.telephony import PhoneChoice
from app.services import agent_registry, conversation
from app.services.telephony import runtime
from app.services.telephony.calls import PhoneCallService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def context(*, admitted: bool = True, live: bool = True) -> RunContext[AgentDeps]:
    deps = AgentDeps(
        organization_id=uuid4() if admitted else None,
        run_person=uuid4() if admitted else None,
        agent_id=uuid4() if admitted else None,
        run_id=uuid4() if admitted else None,
        conversation_id=uuid4(),
        phone_call_id=uuid4() if live else None,
    )
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage(), tool_call_id="phone-1")


@pytest.fixture
def admission(monkeypatch):
    db = AsyncMock()
    actor = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(_toolset, "get_db_context", session)
    member = AsyncMock(return_value=actor)
    monkeypatch.setattr(_toolset, "acting_member", member)
    return db, member


@pytest.mark.parametrize("method", ["get_phone_contact_policy", "call_me"])
async def test_no_person_or_an_impersonator_cannot_request_telephone_contact(method, admission):
    tools = PhoneCallTools(uuid4())
    for ctx in (context(admitted=False), context()):
        if ctx.deps.organization_id is not None:
            ctx.deps.impersonated = True
        assert "admitted member" in await getattr(tools, method)(ctx)
    admission[1].assert_not_awaited()


@pytest.mark.parametrize("method", ["get_phone_contact_policy", "call_me"])
async def test_removed_member_cannot_request_contact(method, admission):
    admission[1].return_value = None
    assert "no longer active" in await getattr(PhoneCallTools(uuid4()), method)(context())
    admission[0].commit.assert_not_awaited()


@pytest.mark.parametrize("change", ["valid", "no_conversation", "missing", "other_agent", "denied"])
async def test_policy_lists_only_current_agent_cases_without_phone_numbers(
    monkeypatch, admission, change
):
    ctx = context()
    if change == "no_conversation":
        ctx.deps.conversation_id = None
    monkeypatch.setattr(
        agent_registry.AgentRegistryService,
        "get",
        AsyncMock(
            side_effect=AuthorizationError(message="agent unavailable")
            if change == "denied"
            else None
        ),
    )
    monkeypatch.setattr(conversation.ConversationService, "get_conversation", AsyncMock())
    contact = SimpleNamespace(
        agent_ids=[] if change == "other_agent" else [str(ctx.deps.agent_id)],
        allow_calls=True,
        allow_reports=True,
        allow_important=True,
        importance_instructions="Only urgent blocks",
        escalation_delay_seconds=300,
        timezone="UTC",
        quiet_start_hour=22,
        quiet_end_hour=7,
    )
    monkeypatch.setattr(
        repo, "contact", AsyncMock(return_value=None if change == "missing" else contact)
    )
    case_id = uuid4()
    cases = AsyncMock(return_value=[SimpleNamespace(id=case_id, summary="x" * 600)])
    monkeypatch.setattr(repo, "open_phone_cases", cases)
    result = await PhoneCallTools(uuid4()).get_phone_contact_policy(ctx)
    if change in ("valid", "no_conversation"):
        parsed = json.loads(result)
        assert parsed["open_cases"] == [{"outcome_id": str(case_id), "summary": "x" * 500}]
        assert parsed["importance_instructions"] == "Only urgent blocks"
        assert "number" not in parsed
        assert cases.await_args.kwargs["conversation_id"] == ctx.deps.conversation_id
    elif change == "denied":
        assert "unavailable" in result
        cases.assert_not_awaited()
    else:
        assert "no telephone contact consent" in result
        cases.assert_not_awaited()


@pytest.mark.parametrize("report", [None, "Read this report"])
@pytest.mark.parametrize("refused", [False, True])
async def test_call_intent_retains_stable_source_and_commits_before_return(
    monkeypatch, admission, report, refused
):
    ctx = context()
    receipt = SimpleNamespace(model_dump_json=lambda: '{"status":"queued"}')
    create = AsyncMock(
        return_value=receipt,
        side_effect=AuthorizationError(message="consent changed") if refused else None,
    )
    monkeypatch.setattr(PhoneCallService, "create", create)
    tools = PhoneCallTools(uuid4())
    result = await tools.call_me(ctx, report=report)
    if refused:
        assert result == "Call refused: consent changed"
        admission[0].commit.assert_not_awaited()
    else:
        assert json.loads(result)["status"] == "queued"
        admission[0].commit.assert_awaited_once()
    data = create.await_args.args[1]
    assert data.mode == ("report" if report else "conversation")
    assert data.agent_id == (None if report else ctx.deps.agent_id)
    assert data.endpoint_id == tools.endpoint_id
    assert create.await_args.kwargs["source_run_id"] == ctx.deps.run_id


@pytest.mark.parametrize(
    "method", ["list_phone_transfer_contacts", "transfer_phone_call", "end_phone_call"]
)
async def test_live_call_tools_refuse_a_run_without_a_call(method, admission):
    args = [uuid4()] if method == "transfer_phone_call" else []
    assert "not holding a telephone call" in await getattr(PhoneCallTools(uuid4()), method)(
        context(live=False), *args
    )
    admission[0].commit.assert_not_awaited()


@pytest.mark.parametrize(
    "method,target",
    [
        ("list_phone_transfer_contacts", "transfer_options"),
        ("transfer_phone_call", "transfer"),
        ("end_phone_call", "end_from_agent"),
    ],
)
@pytest.mark.parametrize("refused", [False, True])
async def test_live_call_tools_pass_both_ownership_identities(
    monkeypatch, admission, method, target, refused
):
    ctx = context()
    tools = PhoneCallTools(uuid4())
    contact = PhoneChoice(id=uuid4(), label="Support")
    action = AsyncMock(
        return_value=[contact],
        side_effect=AuthorizationError(message="ownership changed") if refused else None,
    )
    monkeypatch.setattr(runtime, target, action)
    args = [contact.id] if method == "transfer_phone_call" else []
    result = await getattr(tools, method)(ctx, *args)
    assert action.await_args.kwargs == {
        "source_run_id": ctx.deps.run_id,
        "endpoint_id": tools.endpoint_id,
    }
    assert action.await_args.args[1] == ctx.deps.phone_call_id
    if refused:
        assert "ownership changed" in result
    elif method == "list_phone_transfer_contacts":
        assert str(contact.id) in result and "Support" in result
    elif method == "transfer_phone_call":
        assert "provider accepted" in result
    else:
        assert result == "The call is ending."


async def test_empty_transfer_directory_is_explicit(monkeypatch, admission):
    monkeypatch.setattr(runtime, "transfer_options", AsyncMock(return_value=[]))
    assert (
        await PhoneCallTools(uuid4()).list_phone_transfer_contacts(context())
        == "No transfer contacts are currently available."
    )


def test_phone_binding_requires_validated_configuration_and_explains_contact_limits() -> None:
    from app.agents.capabilities import CapabilityBuildContext
    from app.agents.capabilities.phone_calls import _build
    from app.agents.spec import CapabilityBindingSpec
    from app.schemas.telephony import PhoneCallsConfig

    binding = CapabilityBindingSpec(id="phone_calls")
    with pytest.raises(TypeError, match="validated endpoint"):
        _build(CapabilityBuildContext(binding=binding, config=None))
    endpoint = uuid4()
    capability = _build(
        CapabilityBuildContext(binding=binding, config=PhoneCallsConfig(endpoint_id=endpoint))
    )
    assert capability.endpoint_id == endpoint
    assert "Never claim a queued" in capability.get_instructions()
