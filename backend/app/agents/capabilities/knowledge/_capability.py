"""Knowledge search over the collections an agent is bound to."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.knowledge._toolset import build_knowledge_toolset


class KnowledgeConfig(BaseModel):
    """Per-agent settings for knowledge search."""

    default_top_k: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Passages returned when the model does not ask for a number",
    )
    self_query_enabled: bool = Field(
        default=False,
        description=(
            "Infer FA-039 business filters (source, document type, organizational "
            "unit, date range) from the natural-language query with an LLM when the "
            "model searches without naming any filter itself. Off by default. It can "
            "only narrow within the agent's tenant and collections, never widen."
        ),
    )


@dataclass
class Knowledge(AbstractCapability[AgentDepsT]):
    """Lets an agent search its bound collections.

    Which collections are searchable is not configured here - it is part of the
    agent spec and resolved server-side, so the model cannot widen its own
    reach by asking for a different collection.

    What the tool is *called* is not configured here either, any more: a binding
    says that through `tool_overrides`, which every capability has and which
    the approval gate can see through. See `README.md`.

    ```python
    from pydantic_ai import Agent
    from app.agents.capabilities.knowledge import Knowledge

    agent = Agent('openai:gpt-4.1', capabilities=[Knowledge()])
    ```
    """

    default_top_k: int = 5
    self_query_enabled: bool = False

    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[Any]:
        """The search toolset, built once per capability instance."""
        if self._toolset is None:
            self._toolset = build_knowledge_toolset(
                default_top_k=self.default_top_k,
                self_query_enabled=self.self_query_enabled,
            )
        return self._toolset
