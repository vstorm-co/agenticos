"""Showing the person a draft as a card."""

from dataclasses import dataclass, field

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import RunContext, ToolDefinition
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.drafts._toolset import DraftsToolset
from app.agents.deps import AgentDeps


def _where_the_card_shows(ctx: RunContext[AgentDeps], _tool_def: ToolDefinition) -> bool:
    """Only the web chat draws the card, and a delegate's output never reaches a person."""
    return ctx.deps.shows_drafts and not ctx.deps.delegated


@dataclass
class Drafts(AbstractCapability[AgentDeps]):
    """Lets an agent put text for somebody to send into a card with a copy button.

    No instructions: everything the model needs is the tool's description, which
    it reads only where the tool is offered.
    """

    _toolset: AbstractToolset[AgentDeps] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[AgentDeps]:
        """The draft toolset, offered where the card shows; built once per instance."""
        if self._toolset is None:
            self._toolset = DraftsToolset().filtered(_where_the_card_shows)
        return self._toolset
