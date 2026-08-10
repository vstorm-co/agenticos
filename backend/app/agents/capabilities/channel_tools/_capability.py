"""Channel awareness, built around one bound directory."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.channel_tools._directory import ChannelDirectory
from app.agents.capabilities.channel_tools._toolset import build_channel_toolset


@dataclass
class ChannelTools(AbstractCapability[AgentDepsT]):
    """Lets an agent ask about the channel it is answering in.

    The directory is handed in already bound to one channel and one bot token,
    so nothing here decides *where* to look - the same reason `Knowledge` takes
    the collection names rather than resolving them. The model chooses which
    question to ask; the server has already decided what it may ask it about,
    and which of the four questions it may ask at all.
    """

    directory: ChannelDirectory
    tools: frozenset[str]
    """Which lookups this run's binding allows, by tool id.

    Not defaulted. The whole point of this capability is that the answer differs
    per bound bot, and a default would be a fifth place the answer could come
    from - the one nobody chose."""

    default_limit: int = 20

    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[Any]:
        """The channel toolset, built once per capability instance."""
        if self._toolset is None:
            self._toolset = build_channel_toolset(
                directory=self.directory, default_limit=self.default_limit, tools=self.tools
            )
        return self._toolset
