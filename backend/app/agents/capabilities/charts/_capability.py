"""Rendering charts for the user."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT

from app.agents.capabilities.charts._toolset import ChartsToolset


@dataclass
class Charts(AbstractCapability[AgentDepsT]):
    """Lets an agent draw a chart instead of describing numbers in prose.

    Nothing here is configurable, deliberately: what a chart looks like is the
    model's decision per chart (`chart_type`, `series`, `style`), and the
    palette and defaults belong to whichever surface renders it. A per-agent
    setting would only be a third place to disagree with those two.

    ```python
    from pydantic_ai import Agent
    from app.agents.capabilities.charts import Charts

    agent = Agent('openai:gpt-4.1', capabilities=[Charts()])
    ```
    """

    _toolset: ChartsToolset[AgentDepsT] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> ChartsToolset[AgentDepsT]:
        """The chart toolset, built once per capability instance."""
        if self._toolset is None:
            self._toolset = ChartsToolset[AgentDepsT]()
        return self._toolset
