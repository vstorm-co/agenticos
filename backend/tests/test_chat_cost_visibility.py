"""Spend disclosure is per reader; redaction never changes accounting or answer text."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from itertools import product
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.chat_costs import ChatCostVisibility, chat_cost_policy
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.db.models.deployment_settings import DeploymentSettings
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import deployment_settings_repo, member_repo, organization_repo, user_repo
from app.schemas.agent import AgentRunResult
from app.schemas.console_experience import resolve_chat_costs
from app.schemas.conversation import ConversationCost, MessageList, MessageRead
from app.services.chat_cost_visibility import ChatCostVisibilityService, cost_bearing_chat_frame

pytestmark = pytest.mark.anyio


@dataclass
class Costs:
    ctx: AuthContext
    member: OrganizationMember
    org: Organization
    deployment: DeploymentSettings
    user: User
    service: ChatCostVisibilityService


@pytest.fixture
def costs(monkeypatch: pytest.MonkeyPatch) -> Costs:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")
    member = OrganizationMember(
        user_id=ctx.subject_id, organization_id=ctx.organization_id, role="member"
    )
    org = Organization(
        id=ctx.organization_id, name="Example", slug="example", created_by_user_id=ctx.subject_id
    )
    deployment = DeploymentSettings()
    user = User(id=ctx.subject_id, email="reader@example.com", is_active=True, is_app_admin=False)
    monkeypatch.setattr(member_repo, "get_active", AsyncMock(return_value=member))
    monkeypatch.setattr(organization_repo, "get_by_id", AsyncMock(return_value=org))
    monkeypatch.setattr(deployment_settings_repo, "get", AsyncMock(return_value=deployment))
    monkeypatch.setattr(user_repo, "get_by_id", AsyncMock(return_value=user))
    return Costs(ctx, member, org, deployment, user, ChatCostVisibilityService(AsyncMock()))


@pytest.mark.parametrize(
    ("available", "policy", "preference", "privileged", "eligible"),
    list(
        product(
            (None, True, False),
            ChatCostVisibility,
            (None, True, False),
            (True, False),
            (True, False),
        )
    ),
)
def test_policy_ceiling(
    available: bool | None,
    policy: ChatCostVisibility,
    preference: bool | None,
    privileged: bool,
    eligible: bool,
) -> None:
    result = resolve_chat_costs(
        available, policy, preference, eligible=eligible, spend_privileged=privileged
    )
    permitted = (
        eligible
        and available is not False
        and (
            policy is ChatCostVisibility.EVERYONE
            or (policy is ChatCostVisibility.SPEND_PRIVILEGED and privileged)
        )
    )
    assert result.permitted is permitted
    assert result.effective is (permitted and preference is not False)


def test_invalid_stored_policy_is_not_treated_as_public() -> None:
    assert chat_cost_policy(None) is ChatCostVisibility.EVERYONE
    with pytest.raises(ValueError):
        chat_cost_policy("typo")


async def test_personal_preference_and_live_role_are_fresh(costs: Costs) -> None:
    assert (await costs.service.read(costs.ctx)).effective
    costs.member.chat_costs_visible = False
    assert not await costs.service.visible_for_user(
        organization_id=costs.org.id, user_id=costs.user.id
    )
    costs.member.chat_costs_visible = None
    costs.org.chat_cost_visibility = "spend_privileged"
    costs.member.role = "owner"
    assert await costs.service.visible_for_user(organization_id=costs.org.id, user_id=costs.user.id)
    costs.member.role = "member"
    assert not await costs.service.visible_for_user(
        organization_id=costs.org.id, user_id=costs.user.id
    )
    member_repo.get_active.assert_awaited_with(
        costs.service.db, organization_id=costs.org.id, user_id=costs.user.id
    )


async def test_deleted_disabled_and_removed_readers_cannot_receive_spend(
    costs: Costs, monkeypatch: pytest.MonkeyPatch
) -> None:
    costs.user.is_active = False
    assert not await costs.service.visible_for_user(
        organization_id=costs.org.id, user_id=costs.user.id
    )
    monkeypatch.setattr(user_repo, "get_by_id", AsyncMock(return_value=None))
    assert not await costs.service.visible_for_user(
        organization_id=costs.org.id, user_id=costs.user.id
    )
    monkeypatch.setattr(user_repo, "get_by_id", AsyncMock(return_value=costs.user))
    costs.user.is_active = True
    monkeypatch.setattr(member_repo, "get_active", AsyncMock(return_value=None))
    assert not await costs.service.visible_for_user(
        organization_id=costs.org.id, user_id=costs.user.id
    )
    costs.user.is_app_admin = True
    assert await costs.service.visible_for_user(organization_id=costs.org.id, user_id=costs.user.id)
    costs.user.is_app_admin = False
    assert not await costs.service.visible_for_user(
        organization_id=costs.org.id, user_id=costs.user.id
    )


async def test_anonymous_and_publisher_standins_are_ineligible(costs: Costs) -> None:
    for ctx in (
        AuthContext(user_id=None, organization_id=costs.org.id, role="member"),
        AuthContext(
            user_id=costs.user.id,
            organization_id=costs.org.id,
            role="owner",
            subject_is_publisher_fallback=True,
        ),
    ):
        assert not (await costs.service.read(ctx)).effective
    member_repo.get_active.assert_not_awaited()


async def test_missing_org_and_legacy_deployment(
    costs: Costs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(deployment_settings_repo, "get", AsyncMock(return_value=None))
    assert (await costs.service.read(costs.ctx)).effective
    monkeypatch.setattr(organization_repo, "get_by_id", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError):
        await costs.service.read(costs.ctx)


async def test_transcript_redaction_is_a_copy_and_preserves_tokens_and_text(costs: Costs) -> None:
    now = datetime.now(UTC)
    message = MessageRead(
        id=uuid4(),
        conversation_id=uuid4(),
        role="assistant",
        content="The quote is $10.",
        created_at=now,
        updated_at=now,
        input_tokens=100,
        output_tokens=10,
        cost_usd=Decimal("0.12"),
        cost_is_partial=True,
    )
    data = MessageList(
        items=[message],
        total=1,
        cost=ConversationCost(
            input_tokens=100, output_tokens=10, cost_usd=Decimal("0.12"), cost_is_partial=True
        ),
    )
    assert await costs.service.transcript(costs.ctx, data) is data
    costs.member.chat_costs_visible = False
    result = await costs.service.transcript(costs.ctx, data)
    wire = result.model_dump(mode="json")
    assert "cost_usd" not in wire["items"][0] and "cost_is_partial" not in wire["items"][0]
    assert "cost_usd" not in wire["cost"]
    assert result.items[0].content == message.content and result.items[0].input_tokens == 100
    assert data.items[0].cost_usd == Decimal("0.12") and data.cost.cost_usd == Decimal("0.12")
    assert (await costs.service.transcript(costs.ctx, MessageList(items=[], total=0))).cost is None


async def test_resume_projection_preserves_the_original_result(costs: Costs) -> None:
    data = AgentRunResult(
        run_id=uuid4(),
        output="Saved",
        status="completed",
        cost_usd=Decimal("0.12"),
        input_tokens=10,
        output_tokens=2,
    )
    assert await costs.service.run_result(costs.ctx, data) is data
    costs.org.chat_cost_visibility = "nobody"
    hidden = await costs.service.run_result(costs.ctx, data)
    assert "cost_usd" not in hidden.model_dump(mode="json")
    assert data.cost_usd == Decimal("0.12")


@pytest.mark.parametrize("kind", ("complete", "subagent_complete", "run_answer_result"))
def test_socket_accounting_redaction_copies_only_owned_metadata(kind: str) -> None:
    fields = {
        "cost_usd": "0.12",
        "cost_is_partial": True,
        "budget_percent": 80,
        "agent_budget_percent": 20,
        "input_tokens": 100,
        "output": "$100 quote",
    }
    payload = (
        {"usage": fields}
        if kind == "complete"
        else {"result": fields}
        if kind == "run_answer_result"
        else fields
    )
    frame = cost_bearing_chat_frame(kind, payload)
    assert frame is not None
    redacted = frame.redacted()
    result = (
        redacted["usage"]
        if kind == "complete"
        else redacted["result"]
        if kind == "run_answer_result"
        else redacted
    )
    assert result == {"input_tokens": 100, "output": "$100 quote"}
    assert fields["cost_usd"] == "0.12"


def test_non_accounting_frames_and_unmeasured_usage_are_unchanged() -> None:
    assert cost_bearing_chat_frame("tool_result", {"cost_usd": "quoted tool data"}) is None
    assert cost_bearing_chat_frame("complete", {"usage": None}) is None
    assert cost_bearing_chat_frame("complete", {"usage": {"input_tokens": 2}}) is None
    assert cost_bearing_chat_frame("complete", {"cost_usd": "0.1"}) is not None
    with pytest.raises(ValueError, match="accounting payload"):
        cost_bearing_chat_frame("complete", {"usage": "malformed"})
    with pytest.raises(ValidationError):
        cost_bearing_chat_frame("complete", object())


@pytest.mark.security
async def test_key_scope_cannot_borrow_the_owners_spend_permission(costs: Costs) -> None:
    costs.org.chat_cost_visibility = "spend_privileged"
    assert not (
        await costs.service.read(
            AuthContext(
                user_id=costs.user.id,
                organization_id=costs.org.id,
                role="owner",
                key_scopes=frozenset(),
            )
        )
    ).effective


async def test_full_conversation_projects_without_mutating_saved_messages(costs: Costs) -> None:
    from app.schemas.conversation import ConversationReadWithMessages

    now = datetime.now(UTC)
    data = ConversationReadWithMessages(
        id=uuid4(),
        user_id=costs.user.id,
        organization_id=costs.org.id,
        title="Example",
        created_at=now,
        updated_at=now,
    )
    assert await costs.service.conversation(costs.ctx, data) is data
    costs.deployment.chat_costs_available = False
    hidden = await costs.service.conversation(costs.ctx, data)
    assert hidden is not data and hidden.messages == []


@pytest.mark.parametrize("visible", (True, False))
async def test_live_sender_and_follower_filter_for_their_own_reader(
    costs: Costs, monkeypatch: pytest.MonkeyPatch, visible: bool
) -> None:
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager
    from unittest.mock import MagicMock

    from app.services import agent_session
    from app.services.agent_session import AgentSession

    @asynccontextmanager
    async def database() -> AsyncIterator[AsyncMock]:
        yield costs.service.db

    policy = AsyncMock(return_value=visible)
    monkeypatch.setattr(agent_session, "get_db_context", database)
    monkeypatch.setattr(ChatCostVisibilityService, "visible_for_user", policy)
    websocket = MagicMock()
    websocket.send_json = AsyncMock()
    session = AgentSession(websocket, costs.user, costs.org)
    payload = {"usage": {"cost_usd": "0.12", "input_tokens": 10}}
    session._live_turn = agent_session.live_turn.Turn(str(uuid4()), "writer")
    publish = AsyncMock()
    monkeypatch.setattr(agent_session.live_turn, "publish", publish)
    assert await session._emit("complete", payload)
    publish.assert_awaited_once_with(session._live_turn, "complete", payload)
    sent = websocket.send_json.call_args.args[0]["data"]["usage"]
    assert ("cost_usd" in sent) is visible
    policy.assert_awaited_with(organization_id=costs.org.id, user_id=costs.user.id)

    async def frames(_conversation_id: str, _token: str) -> AsyncIterator[dict[str, object]]:
        yield {"type": "complete", "data": payload}
        yield {"type": agent_session.live_turn.END, "data": {}}

    monkeypatch.setattr(agent_session.live_turn, "follow", frames)
    assert await session._follow_one(str(uuid4()), "attempt")
    assert (
        "cost_usd" in websocket.send_json.call_args_list[-2].args[0]["data"]["usage"]
    ) is visible
    assert payload["usage"]["cost_usd"] == "0.12"


@pytest.mark.parametrize("failure", ("missing", "database", "bug"))
async def test_socket_policy_failure_withholds_only_financial_metadata(
    costs: Costs, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager
    from unittest.mock import MagicMock

    from sqlalchemy.exc import SQLAlchemyError

    from app.services import agent_session
    from app.services.agent_session import AgentSession

    @asynccontextmanager
    async def database() -> AsyncIterator[AsyncMock]:
        yield costs.service.db

    error = (
        NotFoundError(message="Organization not found", details={})
        if failure == "missing"
        else SQLAlchemyError("Unavailable")
        if failure == "database"
        else RuntimeError("A bug")
    )
    monkeypatch.setattr(agent_session, "get_db_context", database)
    monkeypatch.setattr(ChatCostVisibilityService, "visible_for_user", AsyncMock(side_effect=error))
    websocket = MagicMock()
    websocket.send_json = AsyncMock()
    session = AgentSession(websocket, costs.user, costs.org)
    if failure == "bug":
        with pytest.raises(RuntimeError, match="A bug"):
            await session._send_chat_frame("complete", {"usage": {"cost_usd": "0.12"}})
    else:
        assert await session._send_chat_frame(
            "complete", {"usage": {"cost_usd": "0.12", "input_tokens": 10}}
        )
        assert websocket.send_json.call_args.args[0]["data"] == {"usage": {"input_tokens": 10}}
    assert await session._send_chat_frame("text_delta", {"delta": "$100 quote"})
