"""Showing the person a draft as a card."""

from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import RunContext, ToolDefinition
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.drafts._toolset import DraftsToolset
from app.agents.deps import AgentDeps

DRAFT_RULE = (
    "Text the person will send or paste somewhere else (an e-mail, a message, a post) "
    "goes through write_draft. The person sees the card with every part in full, so "
    "your answer never writes the draft out again: not quoted, not paraphrased, not in "
    "a code block. Say at most one short line around it, or nothing. Use square "
    "brackets in a draft only for a detail the person must fill in, such as [Your Name] "
    "or [date], and never invent such a detail; keep brackets already in text the person "
    "gave you or that you are replying to, such as [WIP]."
)


def _card_shows(ctx: RunContext[AgentDeps]) -> bool:
    """Only the web chat draws the card, and a delegate's output never reaches a person."""
    return ctx.deps.shows_drafts and not ctx.deps.delegated


def _where_the_card_shows(ctx: RunContext[AgentDeps], _tool_def: ToolDefinition) -> bool:
    return _card_shows(ctx)


@dataclass
class Drafts(AbstractCapability[AgentDeps]):
    """Lets an agent put text for somebody to send into a card with a copy button.

    The one instruction (`DRAFT_RULE`) says not to write the draft out again in the
    answer and to leave a bracketed placeholder for a detail the model lacks; like
    the tool, it is given only where the card shows.
    """

    _toolset: AbstractToolset[AgentDeps] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[AgentDeps]:
        """The draft toolset, offered where the card shows; built once per instance."""
        if self._toolset is None:
            self._toolset = DraftsToolset().filtered(_where_the_card_shows)
        return self._toolset

    def get_instructions(self) -> Callable[[RunContext[AgentDeps]], str]:
        """The rule for answering around a card, empty where no card shows."""
        return _instructions


def _instructions(ctx: RunContext[AgentDeps]) -> str:
    return DRAFT_RULE if _card_shows(ctx) else ""
