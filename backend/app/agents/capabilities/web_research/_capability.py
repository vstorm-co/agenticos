"""Letting an agent look things up on the public web.

Two shapes, and the choice between them is the one an author actually makes.

*Through a search API* - DuckDuckGo, Tavily, Brave or Exa. We make the request,
so the results come back in one structured payload the chat renders as clickable
sources, and the same agent behaves identically on every model.

*Natively* - the model provider searches, using its own index and its own
citations. No key of ours, usually better results, and only on models that
support it: Pydantic AI raises for those that do not, so the choice is refused
where it cannot work rather than silently doing nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.web_research._search import SearchProvider
from app.agents.capabilities.web_research._toolset import build_toolset


@dataclass
class WebResearch(AbstractCapability[AgentDepsT]):
    """Web search through one of the search APIs we call ourselves."""

    provider: SearchProvider = "duckduckgo"
    max_results: int = 5
    # Unsealed from the vault by the factory. `repr=False` because a dataclass
    # repr is what ends up in a log line and in every traceback frame, and a
    # search key in either is a key that has to be rotated. `None` is normal:
    # DuckDuckGo takes no key, and the tool refuses at call time for the
    # providers that do - publishing refuses the same thing earlier.
    api_key: str | None = field(default=None, repr=False)

    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[Any]:
        if self._toolset is None:
            self._toolset = build_toolset(
                provider=self.provider, api_key=self.api_key, max_results=self.max_results
            )
        return self._toolset
