"""The workspace capability, and the text the model reads about it.

The tools come from `pydantic-ai-backend`, so there is no `_toolset.py` here -
this is the `skills` arrangement, where the library owns the implementation and
this repository owns the presentation. What lives here instead is the tool
declaration, which is used twice and must be one list: registration in
`__init__.py` publishes it to the Builder, and the same descriptions are handed
to the library so the model reads exactly what the catalog shows.

That single source is the point. The person deciding which of these tools needs
approval and the model deciding when to call one should be looking at the same
sentence; two copies in two repositories drift, and nothing reports it.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai_backends import ConsoleCapability, StateBackend

from app.agents.capabilities._registry import CapabilityToolInfo
from app.agents.capabilities.sandbox._permissions import workspace_ruleset

WORKSPACE_TOOLS: tuple[CapabilityToolInfo, ...] = (
    CapabilityToolInfo(
        id="ls",
        description="List the files and directories in the workspace.",
        side_effecting=False,
    ),
    CapabilityToolInfo(
        id="read_file",
        description="Read a file from the workspace.",
        side_effecting=False,
    ),
    CapabilityToolInfo(
        id="glob",
        description="Find files in the workspace by name pattern.",
        side_effecting=False,
    ),
    CapabilityToolInfo(
        id="grep",
        description="Search the workspace's files for a pattern.",
        side_effecting=False,
    ),
    CapabilityToolInfo(
        id="write_file",
        description="Write a file to the workspace, replacing what was there.",
        side_effecting=True,
    ),
    CapabilityToolInfo(
        id="edit_file",
        description="Replace a string inside a file in the workspace.",
        side_effecting=True,
    ),
    CapabilityToolInfo(
        id="execute",
        description="Run a shell command in the workspace.",
        side_effecting=True,
    ),
)
"""Every tool the workspace offers, declared once.

All seven are declared even though a configuration may offer six: a tool absent
from this list cannot be gated by the approval policy or renamed by a binding,
and the dangerous half of that is silent. `execute` in particular stays declared
for the `state` backend, which has no shell - the library answers such a call
with a readable error rather than an exception, and a declaration that comes and
goes with the configuration would mean an approval policy that does too.
"""

TOOL_DESCRIPTIONS = {tool.id: tool.description for tool in WORKSPACE_TOOLS}


def build_workspace(*, backend: Any | None, include_execute: bool) -> ConsoleCapability:
    """The console capability this agent runs with.

    Args:
        backend: The workspace the runner opened, or `None` where there is
            nowhere durable to put files - a preview, a test. An in-memory
            workspace that lives exactly as long as the run is the honest
            answer there, rather than an error about infrastructure the author
            did not ask for.
        include_execute: Whether the shell is offered at all. Off removes it
            rather than gating it, which is a different decision from "ask
            first" and belongs to whoever configured the agent.
    """
    return ConsoleCapability(
        backend=backend if backend is not None else StateBackend(),
        include_execute=include_execute,
        # Four more tools, none of them declared above, and a process left
        # running in a sandbox nobody watches finish. Not offered, so not a
        # configuration somebody can arrive at by accident.
        include_background=False,
        # So `read_file` on an image returns something a multimodal model can
        # see. Without it an agent cannot look at the chart it just rendered,
        # which is most of the reason to let it render one.
        image_support=True,
        document_support=True,
        descriptions=TOOL_DESCRIPTIONS,
        permissions=workspace_ruleset(),
        # Nothing in the ruleset is `"ask"`; this is the backstop for one
        # arriving anyway. Refusing beats raising - a raise ends the run, and
        # this platform's own approval gate is what should be asking.
        ask_fallback="deny",
    )
