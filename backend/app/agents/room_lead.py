"""Planning tools owned by an explicit room request, never by an agent's spec.

Like connect-on-use, this capability belongs to the surface. It is unavailable
outside a human's Ask lead request and can only save a pending proposal.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated, Any
from uuid import UUID

from pydantic import Field
from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.capabilities.abstract import WrapToolExecuteHandler
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities._failures import steer
from app.agents.deps import AgentDeps
from app.agents.spec import AgentSpec
from app.core.exceptions import AppException, BadRequestError
from app.schemas.room_routing import RoomProposalCreate, RoomProposalItem, RoomRoutingProposalRead

PROPOSE_ROOM_TASKS = "propose_room_tasks"
ProposalWriter = Callable[[UUID, RoomProposalCreate], Awaitable[RoomRoutingProposalRead]]


def planning_spec(spec: AgentSpec) -> AgentSpec:
    """Retain the published voice and guardrails while removing executable tools."""
    return spec.model_copy(
        update={
            "capabilities": [
                item for item in spec.capabilities if item.id in {"guardrails", "thinking"}
            ],
            "mcp_servers": [],
            "subagents": [],
            "skill_ids": [],
            "collection_ids": [],
            "code_mode": spec.code_mode.model_copy(update={"enabled": False}),
            "output_schema": None,
        }
    )


@dataclass
class RoomLeadPlanning(AbstractCapability[AgentDeps]):
    context: str
    create_proposal: ProposalWriter = field(repr=False, compare=False)

    def get_instructions(self) -> str:
        return (
            "You are answering an explicit Ask lead request in a project room. "
            "Answer from this room's provided context, or call propose_room_tasks once to offer "
            "at most three bounded handoffs for the requester to review. A proposal does not "
            "create a task or start a specialist. Never claim that proposed work has started, "
            "accept your own proposal, close a task, or send an external message. "
            "Use only the pinned specialists below. Omit accountable_user_id to use the requester; "
            "another eligible member must explicitly start their own assigned agent work. "
            "Existing tasks may be referenced only with their exact current revision and unchanged "
            "assignee. Do not invent task identifiers or revisions. "
            "The person accepts or discards the card in the room; a normal reply needs no tool.\n\n"
            + self.context
        )

    def get_toolset(self) -> FunctionToolset[AgentDeps]:
        tools: FunctionToolset[AgentDeps] = FunctionToolset()
        tools.add_function(self.propose_room_tasks, name=PROPOSE_ROOM_TASKS, takes_ctx=True)
        return tools

    async def prepare_tools(
        self,
        ctx: RunContext[AgentDeps],
        tool_defs: list[ToolDefinition],
    ) -> list[ToolDefinition]:
        return [tool for tool in tool_defs if tool.name == PROPOSE_ROOM_TASKS]

    async def wrap_tool_execute(
        self,
        ctx: RunContext[AgentDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        handler: WrapToolExecuteHandler,
    ) -> Any:
        if tool_def.name != PROPOSE_ROOM_TASKS:
            return "Ask lead can only answer or propose work for human review."
        return await handler(args)

    async def propose_room_tasks(
        self,
        ctx: RunContext[AgentDeps],
        items: Annotated[list[RoomProposalItem], Field(min_length=1, max_length=3)],
    ) -> str:
        """Offer bounded task cards for the requester to review before any work starts.

        Use once when this explicit room request needs a specialist handoff.
        Answer directly when the room context already answers the person's question.

        Args:
            items: One to three handoffs using the pinned specialist ids and versions.
                Each needs a title and expected result. Omit accountable_user_id for
                the requester; an existing task requires its current revision.

        Returns:
            A pending proposal id and stable item ids. Nothing is dispatched.
            Invalid items explain a correction; access refusals are final.
        """
        if ctx.deps.run_id is None:
            return "This planning run is unavailable; no proposal was saved."
        try:
            proposal = await self.create_proposal(ctx.deps.run_id, RoomProposalCreate(items=items))
        except BadRequestError as error:
            return steer(ctx, error.message)
        except AppException:
            return "The routing proposal is unavailable under the requester's current access or policy."
        return (
            f"Pending proposal {proposal.id}; items "
            + ", ".join(str(item.proposal_item_id) for item in proposal.items)
            + ". The requester must accept selected cards before tasks are created or specialists start."
        )
