"""Finding a tool instead of carrying every schema.

Pydantic AI's `ToolSearch` handles discovery: it hides tools marked `defer_loading=True` from
the model until the model discovers them - natively where the provider offers it
(Anthropic BM25/regex, OpenAI server-side), or through a local `search_tools`
function everywhere else.

The subclass selects eligible tools for deferral; the library still owns native
and local discovery. Capability instructions and lifecycle hooks stay active.

Why it needs no metering, unlike most things that touch the model. The local
strategies offered here - `auto`'s keyword fallback, `keywords` and `local_bm25` - run in
Python and spend no tokens; the native strategies run inside the provider's own
request, whose usage the budget guard already meters; and the `search_tools`
round-trips are ordinary model requests the same guard wraps. The one shape that
*would* escape the guard - a custom search callable that itself calls a model or
an embedding - is deliberately not exposed: the config offers named strategies
only, so there is nothing here for the budget to miss (#16 is the live example
of what forgetting this costs).
"""

from dataclasses import dataclass, replace
from typing import Literal

from pydantic_ai.capabilities import ToolSearch, ToolSearchStrategy
from pydantic_ai.tools import RunContext, ToolDefinition
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities._tool_text import ToolText
from app.agents.capabilities.tool_search._ranking import rank_tools

# "auto" is the library's own `None`: native tool search where the provider
# offers it, local keyword matching everywhere else. Kept as an explicit value
# rather than an absent one so the Builder's picker always has something to show.
Strategy = Literal["auto", "keywords", "local_bm25", "bm25", "regex"]

SEARCH_TEXT = ToolText(
    summary=(
        "Search for a deferred tool when the tools you already have, and the "
        "capability catalog, do not name the operation you need."
    ),
    usage=(
        "Search can find deferred tools from enabled capabilities and connected MCP servers. "
        "For a skill in the capability catalog, load the capability by id instead. "
        "Search cannot enable a capability or connect a server."
    ),
    returns=(
        "The matching tools with their descriptions, which become callable once "
        "found. An empty answer means no such tool is deferred here, not that "
        "the query was wrong, so do not search again for the same thing."
    ),
)
"""What the model reads about `search_tools`.

The library's own text is prose with no return shape - and this is the tool a
model reaches for when it is already lost, which is the worst moment to leave it
guessing what an empty answer means. `parameter_description` is left to the
library: its default already says what a query is and that queries are unioned.
"""


@dataclass
class ConfiguredToolSearch(ToolSearch[object]):
    """Select function tools for discovery without deferring capability lifecycle hooks.

    The factory supplies effective tool names from its enabled bindings, including
    tools contributed by child capabilities. Surface-added tools such as account
    connection and capability requests must remain visible.
    Exclusions preserve existing deferred flags, including skill disclosure gates.
    """

    defer_capabilities: bool = False
    defer_mcp_servers: bool = True
    exclude_capabilities: frozenset[str] = frozenset()
    exclude_mcp_servers: frozenset[str] = frozenset()
    exclude_tools: frozenset[str] = frozenset()
    capability_tool_names: frozenset[str] = frozenset()

    async def prepare_tools(
        self, ctx: RunContext[object], tool_defs: list[ToolDefinition]
    ) -> list[ToolDefinition]:
        # Pydantic AI dispatches this after ownership and renames, inside its
        # search wrapper. Only function schemas change; hooks and builtins do not.
        return [
            replace(tool, defer_loading=True)
            if self.defer_capabilities
            and tool.capability_id is not None
            and tool.name in self.capability_tool_names
            and tool.name not in self.exclude_tools
            else tool
            for tool in tool_defs
        ]

    def defer_toolset(self, toolset: AbstractToolset[object]) -> AbstractToolset[object]:
        """Defer one resolved MCP server, using its leaf id through public wrappers."""
        server_ids: set[str] = set()

        def remember_server(child: AbstractToolset[object]) -> None:
            if child.id is not None:
                server_ids.add(child.id)

        toolset.apply(remember_server)
        if not self.defer_mcp_servers or server_ids & {
            f"mcp-{prefix}" for prefix in self.exclude_mcp_servers
        }:
            return toolset
        if not self.exclude_tools:
            return toolset.defer_loading()
        return toolset.prepared(self._defer_mcp_tools)

    def _defer_mcp_tools(
        self, ctx: RunContext[object], tool_defs: list[ToolDefinition]
    ) -> list[ToolDefinition]:
        return [
            tool if tool.name in self.exclude_tools else replace(tool, defer_loading=True)
            for tool in tool_defs
        ]


def build_tool_search(
    strategy: Strategy,
    max_results: int,
    *,
    defer_capabilities: bool = False,
    defer_mcp_servers: bool = True,
    exclude_capabilities: frozenset[str] = frozenset(),
    exclude_mcp_servers: frozenset[str] = frozenset(),
    exclude_tools: frozenset[str] = frozenset(),
) -> ConfiguredToolSearch:
    """Turn a chosen strategy into the capability that carries it.

    `auto` maps to the library's `None` - let Pydantic AI pick native on a
    provider that supports it and fall back to the local keyword algorithm
    otherwise. The named strategies pass straight through: `keywords` always runs
    locally, and `bm25`/`regex` force an Anthropic-native algorithm and raise at
    request time on a provider that cannot honour them - a run-time cost the
    author accepts by naming one, since the model is resolved separately and this
    capability cannot see it at publish.
    """
    named: ToolSearchStrategy[object] | None
    named = rank_tools if strategy == "local_bm25" else None if strategy == "auto" else strategy
    return ConfiguredToolSearch(
        strategy=named,
        max_results=max_results,
        tool_description=SEARCH_TEXT.render(),
        defer_capabilities=defer_capabilities,
        defer_mcp_servers=defer_mcp_servers,
        exclude_capabilities=exclude_capabilities,
        exclude_mcp_servers=exclude_mcp_servers,
        exclude_tools=exclude_tools,
    )
