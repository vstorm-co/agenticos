"""Reading published skill instructions is not an unattended external action (#3019)."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic_ai.tools import ToolDefinition
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.skills._loader import SKILL_LOAD_KIND
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.services.routine_authority import RoutineAuthority

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize(
    "name,kind,enabled,required",
    [
        ("read_skill", SKILL_LOAD_KIND, True, False),
        ("read_skill", None, True, True),
        ("read_skill", SKILL_LOAD_KIND, False, True),
        ("other_framework_tool", SKILL_LOAD_KIND, True, True),
    ],
)
async def test_only_the_owned_loader_is_a_read(name, kind, enabled, required):
    from collections.abc import AsyncIterator

    authority = RoutineAuthority(
        routine_id=uuid4(),
        organization_id=uuid4(),
        user_id=uuid4(),
        root_agent_id=uuid4(),
        role="owner",
        acts_as_creator=True,
    )
    db = AsyncMock(spec=AsyncSession)

    @asynccontextmanager
    async def context() -> AsyncIterator[AsyncSession]:
        yield db

    spec = AgentSpec(
        name="Scheduled assistant",
        capabilities=[CapabilityBindingSpec(id="skills", enabled=enabled)],
    )
    with (
        patch("app.services.routine_authority.get_db_context", context),
        patch.object(RoutineAuthority, "check_in", AsyncMock()) as check,
    ):
        result = await authority.action_policy(
            authority.root_agent_id, spec, ToolDefinition(name=name, tool_kind=kind)
        )
        assert result.required is required
        check.assert_awaited_once_with(db, authority.root_agent_id)


async def test_a_real_native_skill_load_finishes_unattended_but_explicit_gating_still_parks():
    from collections.abc import AsyncIterator

    from pydantic_ai import Agent, DeferredToolRequests
    from pydantic_ai.models.function import FunctionModel

    from app.agents.approval import ApprovalPending
    from app.agents.capabilities.approval._capability import ApprovalGate
    from app.agents.capabilities.skills._loader import SkillLoader
    from app.agents.deps import AgentDeps
    from tests.test_read_skill_loader import _read_then_finish, _skill

    authority = RoutineAuthority(
        routine_id=uuid4(),
        organization_id=uuid4(),
        user_id=uuid4(),
        root_agent_id=uuid4(),
        role="owner",
        acts_as_creator=True,
    )
    spec = AgentSpec(name="Scheduled assistant", capabilities=[CapabilityBindingSpec(id="skills")])
    db = AsyncMock(spec=AsyncSession)

    @asynccontextmanager
    async def context() -> AsyncIterator[AsyncSession]:
        yield db

    async def policy(tool: ToolDefinition):
        return await authority.action_policy(authority.root_agent_id, spec, tool)

    with (
        patch("app.services.routine_authority.get_db_context", context),
        patch.object(RoutineAuthority, "check_in", AsyncMock()),
    ):
        plain = Agent(
            FunctionModel(_read_then_finish),
            deps_type=AgentDeps,
            capabilities=[SkillLoader(), _skill(), ApprovalGate(routine_policy=policy)],
        )
        assert (await plain.run("Read the refund skill", deps=AgentDeps())).output == "done"
        explicit = Agent(
            FunctionModel(_read_then_finish),
            deps_type=AgentDeps,
            output_type=[str, DeferredToolRequests],
            capabilities=[
                SkillLoader(),
                _skill(),
                ApprovalGate(routine_policy=policy, required_tool_names=frozenset({"read_skill"})),
            ],
        )
        assert isinstance(
            (
                await explicit.run(
                    "Read the refund skill",
                    deps=AgentDeps(request_approval=AsyncMock(return_value=ApprovalPending())),
                )
            ).output,
            DeferredToolRequests,
        )
