"""A pinned version runs as it was published, under the approvals the agent has now.

A routine, an environment or a workflow step can pin an older version, and a
parked run resumes on the version it parked on. That version keeps its
instructions, tools and model; who must approve a tool call is the current
published version's to say - `docs/governance.md`: "current access, budgets and
approvals still apply".
"""

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities import load_builtins
from app.agents.capabilities.approval import approval_required_tools, with_current_approvals
from app.agents.spec import AgentSpec
from app.core.permissions import AuthContext, OrgRoleName
from app.services.agent_runner import AgentRunnerService

pytestmark = pytest.mark.anyio

MEMORY = "memory_files"


@pytest.fixture(autouse=True)
def _builtins_loaded() -> None:
    load_builtins()


def _memory(**binding: Any) -> AgentSpec:
    return AgentSpec(name="Support", instructions="Help.", capabilities=[{"id": MEMORY, **binding}])


UNGATED = _memory()
GATED = _memory(tool_approval={"write_memory": "required"})


def _db() -> MagicMock:
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    db.scalar = AsyncMock(return_value=0)
    db.get = AsyncMock(return_value=MagicMock(monthly_budget_usd=None))
    return db


class TestWhatAPinnedRunIsBuiltWith:
    async def _built_spec(self, pinned: AgentSpec, current: AgentSpec | None) -> AgentSpec:
        ctx = AuthContext(
            user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER
        )
        service = AgentRunnerService(_db())
        current_id, pinned_id = uuid.uuid4(), uuid.uuid4()
        agent = MagicMock(
            id=uuid.uuid4(),
            organization_id=ctx.organization_id,
            current_version_id=current_id,
            system_key=None,
            kind="agent",
        )
        version = None if current is None else SimpleNamespace(spec=current.model_dump(mode="json"))
        with (
            patch.object(
                service.registry,
                "get_runnable_spec",
                new=AsyncMock(return_value=(agent, pinned, pinned_id)),
            ),
            patch(
                "app.services.agent_runner.agent_repo.published_budget_caps",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.services.agent_runner.agent_repo.get_version",
                new=AsyncMock(return_value=version),
            ),
            patch(
                "app.services.agent_runner.user_repo.get_by_id", new=AsyncMock(return_value=None)
            ),
            patch(
                "app.services.agent_runner.group_repo.names_for_member",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.agent_runner.group_repo.capped_groups_for_member",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                service.models, "resolve", new=AsyncMock(return_value=MagicMock(label="gpt-4.1"))
            ),
            patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
            patch(
                "app.services.agent_runner.agent_run_repo.create_run",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ),
            patch("app.services.agent_runner.build_agent") as build,
        ):
            await service.prepare(ctx, agent.id)

        built: AgentSpec = build.call_args.args[0]
        return built

    async def test_a_tool_the_current_version_gates_waits_on_the_pinned_one(self) -> None:
        built = await self._built_spec(UNGATED, GATED)

        assert "write_memory" in approval_required_tools(built)

    async def test_a_gate_the_current_version_removed_no_longer_holds(self) -> None:
        built = await self._built_spec(GATED, UNGATED)

        assert "write_memory" not in approval_required_tools(built)

    async def test_a_current_version_that_cannot_be_read_leaves_the_pinned_ones(self) -> None:
        built = await self._built_spec(UNGATED, None)

        assert "write_memory" not in approval_required_tools(built)


class TestWhichApprovalsCarryOver:
    def test_only_the_approval_settings_move(self) -> None:
        pinned = AgentSpec(
            name="Support",
            instructions="Answer as v1.",
            capabilities=[{"id": MEMORY, "config": {"allow_personal": False}}],
        )
        current = AgentSpec(
            name="Support",
            instructions="Answer as v2.",
            capabilities=[
                {
                    "id": MEMORY,
                    "approval": "required",
                    "tool_approval": {"recall": "never"},
                    "config": {"allow_personal": True},
                }
            ],
        )

        merged = with_current_approvals(pinned, current)

        assert merged.instructions == "Answer as v1."
        [binding] = merged.capabilities
        assert binding.config == {"allow_personal": False}
        assert binding.approval == "required"
        assert binding.tool_approval == {"recall": "never"}

    def test_a_capability_the_current_version_dropped_keeps_its_own(self) -> None:
        pinned = _memory(tool_approval={"write_memory": "required"})

        merged = with_current_approvals(pinned, AgentSpec(name="Support"))

        assert merged.capabilities[0].tool_approval == {"write_memory": "required"}

    def test_mcp_approvals_follow_the_same_server(self) -> None:
        connection, other = uuid.uuid4(), uuid.uuid4()
        pinned = AgentSpec(
            name="Support",
            mcp_servers=[
                {"connection_id": str(connection), "approval": "none"},
                {"connection_id": str(other), "approval": "none"},
                {"account": "personal", "catalog_key": "notion", "approval": "none"},
                {"account": "platform", "approval": "writes"},
            ],
        )
        current = AgentSpec(
            name="Support",
            mcp_servers=[
                {
                    "connection_id": str(connection),
                    "approval": "all",
                    "tool_approval": {"delete_page": "required"},
                },
                {"account": "personal", "catalog_key": "notion", "approval": "writes"},
                {"account": "platform", "approval": "all"},
            ],
        )

        merged = with_current_approvals(pinned, current)

        approvals = [ref.approval for ref in merged.mcp_servers]
        assert approvals == ["all", "none", "writes", "all"]
        assert merged.mcp_servers[0].tool_approval == {"delete_page": "required"}


class TestWhenTheCurrentVersionIsNotConsulted:
    async def test_the_current_version_a_draft_and_an_unpublished_agent_keep_their_own(
        self,
    ) -> None:
        get_version = AsyncMock()
        service = AgentRunnerService(MagicMock())
        current = uuid.uuid4()

        with patch("app.services.agent_runner.agent_repo.get_version", new=get_version):
            for agent, version_id in (
                (MagicMock(current_version_id=current), current),
                (MagicMock(current_version_id=current), None),
                (MagicMock(current_version_id=None), uuid.uuid4()),
            ):
                assert (
                    await service._with_current_approvals(agent, UNGATED, version_id=version_id)
                    is UNGATED
                )

        get_version.assert_not_awaited()
