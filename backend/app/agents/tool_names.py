"""The names a run gives tools other than an MCP server's, and whose each is (#2890).

Pydantic AI answers two tools of one name by aborting the turn. A connection's
prefix keeps one MCP server's tools apart from another's, but not from these: a
connection `request` whose server offers `capability` presents
`request_capability`, which nearly every agent has. And a capability's rename can
land on another capability's tool. Publish and the run both read the names to
keep off from here.
"""

from app.agents.capabilities import FRAMEWORK_TOOL_NAMES, all_capabilities
from app.agents.capabilities.channel_tools import CHANNEL_TOOLS_CAPABILITY_ID
from app.agents.computer_on_use import REQUEST_COMPUTER_ACCESS
from app.agents.connect_on_use import CONNECT_ACCOUNT
from app.agents.hand_off import HAND_OFF_TOOL
from app.agents.setup_briefing import REQUEST_CAPABILITY
from app.agents.spec import AgentSpec

PLATFORM_TOOL_NAMES = frozenset(
    {
        *FRAMEWORK_TOOL_NAMES,
        REQUEST_CAPABILITY,
        # Pydantic AI's own, once tool search wraps a deferred toolset.
        "search_tools",
        # Pydantic AI's output tool, for a run asked for a structured answer - by
        # the spec's `output_schema` or by the request itself.
        "final_result",
        CONNECT_ACCOUNT,
        REQUEST_COMPUTER_ACCESS,
        HAND_OFF_TOOL,
    }
)
"""The tools the platform adds to a run beside its capabilities'.

`request_capability` on nearly every agent, a loader with a deferred capability
or a skill, `search_tools` with tool search, `final_result` for a structured
answer, and on the surfaces that can wait for a person or hand a call to its
twin, `connect_account`, `request_computer_access` and `hand_off`.
"""


def taken_tool_names(spec: AgentSpec) -> dict[str, str]:
    """Every name a run of `spec` may give a tool that is not an MCP server's, and whose.

    A capability's tools under the names its binding gives them. The platform's
    own for every agent, whether or not this run's surface adds them: publish
    cannot know the surface, and a name free in the console and taken in Slack
    would be an agent that works in one of them. For the same reason the channel
    tools are held on every agent: a channel's binding adds them per run, never
    the published spec. A capability the registry does not hold is left out -
    publish refuses it on its own, and it never runs.
    """
    taken = dict.fromkeys(PLATFORM_TOOL_NAMES, "this platform")
    known = {definition.id: definition for definition in all_capabilities()}
    channel = f"the {CHANNEL_TOOLS_CAPABILITY_ID} capability"
    taken.update(
        dict.fromkeys((tool.name for tool in known[CHANNEL_TOOLS_CAPABILITY_ID].tools), channel)
    )
    for binding in spec.capabilities:
        definition = known.get(binding.id)
        if definition is None or not binding.enabled:
            continue
        for tool in definition.effective_tools(binding.tool_overrides):
            taken[tool.name] = f"the {binding.id} capability"
    return taken
