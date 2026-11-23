"""Following an agent adds no extra action gate and preserves the real gate."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic_ai import ApprovalRequired
from pydantic_ai.tools import ToolDefinition
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.approval import ApprovalPending
from app.agents.capabilities.approval import ApprovalGate
from app.agents.mcp import ALWAYS_ASKS, PLATFORM_TOOL
from app.agents.spec import AgentSpec
from app.schemas.routine_sources import RoutineSourcePolicy
from app.services.routine_authority import RoutineAuthority
from tests.test_approval_gate import _call, _ctx, _Recorder

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize(
    "gate_kind",
    ["free", "agent_required", "mandatory_platform", "reporter_free", "reporter_required"],
)
async def test_follow_agent_sending_uses_the_real_agent_and_mandatory_gates(gate_kind: str):
    person = uuid4()
    policy = RoutineSourcePolicy(
        mode="follow_agent",
        id=uuid4(),
        consented_by=person,
        reviewed_at=datetime.now(UTC),
        version_id=uuid4(),
        scope_hash="a" * 64,
        spec_hash="b" * 64,
    )
    authority = RoutineAuthority(
        routine_id=uuid4(),
        organization_id=uuid4(),
        user_id=person,
        root_agent_id=uuid4(),
        role="owner",
        acts_as_creator=True,
        source_policy=policy,
        action_mode="manual" if gate_kind.startswith("reporter") else None,
    )
    db = AsyncMock(spec=AsyncSession)

    @asynccontextmanager
    async def context() -> AsyncIterator[AsyncSession]:
        yield db

    name = (
        "agenticos_publish_inbox_finding"
        if gate_kind.startswith("reporter")
        else "agenticos_publish_workflow"
        if gate_kind == "mandatory_platform"
        else "send_chat_message"
    )
    definition = ToolDefinition(
        name=name,
        capability_id=None if gate_kind == "mandatory_platform" else "channel_actions",
        metadata={PLATFORM_TOOL: True}
        if gate_kind.startswith("reporter")
        else {ALWAYS_ASKS: True}
        if gate_kind == "mandatory_platform"
        else None,
    )
    spec = AgentSpec(name="Digest")

    async def routine(tool: ToolDefinition):
        return await authority.action_policy(authority.root_agent_id, spec, tool)

    gate = ApprovalGate(
        routine_policy=routine,
        required_tool_names=frozenset({name})
        if gate_kind in {"agent_required", "reporter_required"}
        else frozenset(),
    )
    ctx = _ctx(None)
    callback = AsyncMock(return_value=ApprovalPending())
    ctx.deps.request_approval = callback
    handler = _Recorder()
    with (
        patch("app.services.routine_authority.get_db_context", context),
        patch.object(RoutineAuthority, "check_in", AsyncMock()) as check,
    ):
        if gate_kind in {"free", "reporter_free"}:
            assert (
                await gate.wrap_tool_execute(
                    ctx, call=_call({}), tool_def=definition, args={}, handler=handler
                )
                == "sent"
            )
            assert handler.calls == [{}]
            callback.assert_not_awaited()
        else:
            with pytest.raises(ApprovalRequired):
                await gate.wrap_tool_execute(
                    ctx, call=_call({}), tool_def=definition, args={}, handler=handler
                )
            assert handler.calls == []
            assert callback.await_args.args[0].routine_consented_by is None
        check.assert_awaited_once_with(db, authority.root_agent_id)


@pytest.mark.parametrize(
    "invalid", ["nested", "restricted_parent", "restricted_child", "unproved_child"]
)
async def test_an_approved_ceiling_cannot_nest_or_borrow_an_unproved_policy(invalid: str):
    from pydantic import ValidationError

    base = RoutineSourcePolicy(
        mode="follow_agent",
        id=uuid4(),
        consented_by=uuid4(),
        reviewed_at=datetime.now(UTC),
        version_id=uuid4(),
        scope_hash="a" * 64,
        spec_hash="b" * 64,
        behavior={"root": "c" * 64},
    ).model_dump(mode="json")
    child = dict(base)
    parent = {**base, "approved_ceiling": child}
    if invalid == "nested":
        child["approved_ceiling"] = dict(base)
    elif invalid == "restricted_parent":
        parent["mode"] = "restricted"
    elif invalid == "restricted_child":
        child["mode"] = "restricted"
    else:
        child["behavior"] = None
    with pytest.raises(ValidationError, match="non-nested following behavior snapshot"):
        RoutineSourcePolicy.model_validate(parent)


@pytest.mark.parametrize("consented", [False, True])
async def test_following_sources_support_per_tool_approval_choices(consented: bool):
    from app.agents.spec import CapabilityBindingSpec

    person = uuid4()
    policy = RoutineSourcePolicy(
        mode="follow_agent",
        id=uuid4(),
        consented_by=person,
        reviewed_at=datetime.now(UTC),
        version_id=uuid4(),
        scope_hash="a" * 64,
        spec_hash="b" * 64,
    )
    authority = RoutineAuthority(
        routine_id=uuid4(),
        organization_id=uuid4(),
        user_id=person,
        root_agent_id=uuid4(),
        role="owner",
        acts_as_creator=True,
        source_policy=policy,
        action_mode="per_tool",
    )
    db = AsyncMock(spec=AsyncSession)

    @asynccontextmanager
    async def context() -> AsyncIterator[AsyncSession]:
        yield db

    with (
        patch("app.services.routine_authority.get_db_context", context),
        patch.object(RoutineAuthority, "check_in", AsyncMock()),
        patch(
            "app.services.routine_authority.agent_trigger_repo.get_by_id",
            AsyncMock(return_value=None),
        ),
        patch.object(
            RoutineAuthority, "_consent_in", AsyncMock(return_value=person if consented else None)
        ),
    ):
        decision = await authority.action_policy(
            authority.root_agent_id,
            AgentSpec(name="Worker", capabilities=[CapabilityBindingSpec(id="sandbox")]),
            ToolDefinition(name="execute", capability_id="sandbox"),
        )
    assert decision.required
    assert decision.consented_by == (person if consented else None)
