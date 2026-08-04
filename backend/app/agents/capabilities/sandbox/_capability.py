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

from pydantic_ai_backends import (
    AsyncBackendProtocol,
    BackendProtocol,
    ConsoleCapability,
    StateBackend,
)
from pydantic_ai_backends.toolsets import descriptions as console_text

from app.agents.capabilities._registry import CapabilityToolInfo
from app.agents.capabilities.sandbox._permissions import workspace_ruleset

WORKSPACE_TOOLS: tuple[CapabilityToolInfo, ...] = (
    CapabilityToolInfo(id="ls", description=console_text.LS_DESCRIPTION, side_effecting=False),
    CapabilityToolInfo(
        id="read_file", description=console_text.READ_FILE_DESCRIPTION, side_effecting=False
    ),
    CapabilityToolInfo(id="glob", description=console_text.GLOB_DESCRIPTION, side_effecting=False),
    CapabilityToolInfo(id="grep", description=console_text.GREP_DESCRIPTION, side_effecting=False),
    CapabilityToolInfo(
        id="write_file", description=console_text.WRITE_FILE_DESCRIPTION, side_effecting=False
    ),
    CapabilityToolInfo(
        id="edit_file", description=console_text.EDIT_FILE_DESCRIPTION, side_effecting=False
    ),
    CapabilityToolInfo(
        id="execute", description=console_text.EXECUTE_DESCRIPTION, side_effecting=True
    ),
)
"""Every tool the workspace offers, declared once, with the library's own text.

All seven are declared even though a configuration may offer six: a tool absent
from this list cannot be gated by the approval policy or renamed by a binding,
and the dangerous half of that is silent. `execute` in particular stays declared
for the `state` backend, which has no shell - the library answers such a call
with a readable error rather than an exception, and a declaration that comes and
goes with the configuration would mean an approval policy that does too.

The descriptions are **imported, not written here**, and the direction matters.
The catalog is built from docstrings, and this library puts its tool text in the
decorator instead - so a first attempt at making the two agree pushed a
one-line summary of each tool *into* the toolset, and the model stopped reading
the text that was actually worth reading: that `glob` is the tool for finding
files by pattern and `ls` for seeing one directory, that a file must be read
before it is edited, how to paginate a long one, and two and a half thousand
characters about what a shell command may and may not assume. A tool's
description is the strongest prompt in the product; replacing it with a label
for a form is a downgrade wearing consistency as an excuse. So the label follows
the prompt.

**Only `execute` is side-effecting.** Writing a file used to be too, and that was
wrong in a way only visible from using it: a workspace is scratch space deleted
with the conversation it belongs to, so `write_file` is not the same class of act
as sending an email - and an agent that must ask before every write cannot do
multi-step work at all. The author's move then is to turn the gate off entirely,
which loses the one that mattered. `execute` runs arbitrary commands on somebody's
host; it is what `sandbox:execute` exists for, and it is the one worth a person
looking. A binding that wants the stricter behaviour still gets it with one
`tool_approval` override.
"""


def build_workspace(
    *, backend: BackendProtocol | AsyncBackendProtocol | None, include_execute: bool
) -> ConsoleCapability:
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
        # No `descriptions=`: what the library registers is what the catalog
        # declares, so there is nothing to override and no second copy to drift.
        #
        # `permissions=` is what enforces the off-limits paths, as of
        # pydantic-ai-backend 0.2.25. It used to reach only the approval flags and
        # the drop-a-denied-operation's-tools check, so this repository wrapped the
        # backend itself to make the patterns mean anything; vstorm-co/pydantic-ai-backend#97
        # moved that into the library, where it also covers `grep` filtering and
        # the command-argument check, and the wrapper here was deleted.
        permissions=workspace_ruleset(),
        # Nothing in the ruleset is `"ask"`; this is the backstop for one
        # arriving anyway. Refusing beats raising - a raise ends the run, and
        # this platform's own approval gate is what should be asking.
        ask_fallback="deny",
    )
