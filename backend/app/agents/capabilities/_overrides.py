"""Presenting a capability's tools under the names one agent chose.

A tool's description is the highest-leverage prompt in the product - it is the
last thing the model reads before deciding whether to act - and the name is read
with it. The same search is `search_refund_policy` for one agent and
`search_orders` for another, and steering a model usually means rewording a tool
rather than writing a second one.

Applied by wrapping the capability rather than by each capability offering its
own rename field: a mechanism a capability author has to remember to provide is
a mechanism five of six capabilities will not have. Wrapping also keeps the
rewrite *narrow* - only the wrapped capability's tools change, so an MCP server
that happens to expose a tool of the same name is left alone, exactly as the
approval gate leaves it alone.

The identity a rename must not touch is the tool's `id`. Approval is keyed on
it, and `CapabilityDef.effective_tools` is what turns that id back into the name
the gate has to match.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from pydantic_ai.capabilities import WrapperCapability
from pydantic_ai.tools import AgentDepsT, RunContext, ToolDefinition
from pydantic_ai.toolsets import AbstractToolset, AgentToolset


@dataclass
class ToolOverrides(WrapperCapability[AgentDepsT]):
    """Wraps a capability so its tools reach the model as one agent wants them.

    Both maps are keyed by the tool's stable id, which is the name the wrapped
    toolset offers. Renaming happens outside the description rewrite so the
    rewrite still sees the ids it was configured with.
    """

    names: dict[str, str] = field(default_factory=dict)
    """Stable tool id -> the name the model calls it by."""

    descriptions: dict[str, str] = field(default_factory=dict)
    """Stable tool id -> what the model reads before calling it."""

    def get_toolset(self) -> AgentToolset[AgentDepsT] | None:
        toolset = super().get_toolset()
        if toolset is None:
            return None
        if not isinstance(toolset, AbstractToolset):
            # A capability whose toolset is a per-run function has no tool list
            # to rename here. Returning it untouched would leave an agent whose
            # spec says one thing and whose model sees another, with nothing
            # reporting the difference - including to the approval gate, which
            # would then be watching for a name the model never calls.
            raise TypeError(
                f"Capability {self.id!r} resolves its toolset per run, "
                "so its tools cannot be renamed by a binding"
            )
        # `renamed` maps the new name back to the original, so it is inverted
        # from the way a binding states it.
        return toolset.prepared(self._describe).renamed(
            {name: tool_id for tool_id, name in self.names.items()}
        )

    # `RunContext[object]` rather than `RunContext[AgentDepsT]`: narrowing the
    # toolset to `AbstractToolset` above erases its dependency type, and this
    # rewrite reads none of it.
    def _describe(
        self, _ctx: RunContext[object], tool_defs: list[ToolDefinition]
    ) -> list[ToolDefinition]:
        """Reword the tools this binding has an opinion about, and no others."""
        return [
            tool_def
            if (description := self.descriptions.get(tool_def.name)) is None
            else replace(tool_def, description=description)
            for tool_def in tool_defs
        ]
