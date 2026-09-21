"""Knowledge search over the collections an agent is bound to."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.knowledge._toolset import build_knowledge_toolset
from app.services.rag.query_analysis import QueryAnalysisMode


class KnowledgeConfig(BaseModel):
    """Per-agent settings for knowledge search."""

    default_top_k: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Passages returned when the model does not ask for a number",
    )
    query_analysis_mode: QueryAnalysisMode = Field(
        default="off",
        description=(
            "Optionally analyse and expand the query before retrieval to improve "
            "recall on short or fuzzy questions. Off by default. `keywords` costs "
            "nothing; `multi_query` and `hyde` each make one extra model call"
        ),
        # Flat scalar/enum fields, and labels the Builder renders in the picker:
        # the values are spec format and cannot say what they do, and the guess
        # that costs money is the one that turns on an LLM mode unknowingly. Same
        # `x-enum-labels` mechanism as CompactionConfig.strategy.
        json_schema_extra={
            "x-enum-labels": {
                "off": "Off - search the query as written",
                "keywords": "Keywords - boost the query's own terms (no model call)",
                "multi_query": "Multi-query - search rephrasings too (one model call)",
                "hyde": "HyDE - search a hypothetical answer's embedding (one model call)",
            }
        },
    )
    query_analysis_max_variants: int = Field(
        default=3,
        ge=1,
        le=5,
        description=(
            "How many rephrasings `multi_query` may add, bounding its fan-out and "
            "cost. Ignored by the other modes"
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
    query_analysis_mode: QueryAnalysisMode = "off"
    query_analysis_max_variants: int = 3

    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[Any]:
        """The search toolset, built once per capability instance."""
        if self._toolset is None:
            self._toolset = build_knowledge_toolset(
                default_top_k=self.default_top_k,
                query_analysis_mode=self.query_analysis_mode,
                query_analysis_max_variants=self.query_analysis_max_variants,
            )
        return self._toolset
