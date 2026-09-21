"""Knowledge search over the collections an agent is bound to."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.knowledge._toolset import build_knowledge_toolset
from app.services.rag.models import ParentContextMode


class KnowledgeConfig(BaseModel):
    """Per-agent settings for knowledge search."""

    default_top_k: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Passages returned when the model does not ask for a number",
    )
    parent_context: ParentContextMode = Field(
        default=ParentContextMode.OFF,
        description=(
            "Small-to-big retrieval: return each matched chunk with its "
            "surrounding context. 'off' returns the matched chunk alone (the "
            "default), 'window' adds its neighbours in the same document, "
            "'parent' returns the whole parent document. Matching and ranking "
            "always run on the small chunks; the returned context is bounded."
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
    parent_context: ParentContextMode = ParentContextMode.OFF

    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[Any]:
        """The search toolset, built once per capability instance."""
        if self._toolset is None:
            self._toolset = build_knowledge_toolset(
                default_top_k=self.default_top_k, parent_context=self.parent_context
            )
        return self._toolset
