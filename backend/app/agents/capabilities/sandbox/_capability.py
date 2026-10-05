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

from pydantic_ai.capabilities import CombinedCapability
from pydantic_ai_backends import ConsoleCapability, StateWorkspace
from pydantic_ai_backends.toolsets.descriptions import TOOL_TEXT

from app.agents.capabilities._registry import CapabilityToolInfo
from app.agents.capabilities.sandbox._permissions import workspace_ruleset

WORKSPACE_TOOLS: tuple[CapabilityToolInfo, ...] = tuple(
    CapabilityToolInfo(
        id=tool_id,
        description=TOOL_TEXT[tool_id].summary,
        side_effecting=tool_id == "execute",
    )
    for tool_id in ("ls", "read_file", "glob", "grep", "write_file", "edit_file", "execute")
)
"""Every tool the workspace offers, declared once, with the library's own text.

All seven are declared even though a configuration may offer six: a tool absent
from this list cannot be gated by the approval policy or renamed by a binding,
and the dangerous half of that is silent. `execute` in particular stays declared
for the `state` backend, which has no shell - the library answers such a call
with a readable error rather than an exception, and a declaration that comes and
goes with the configuration would mean an approval policy that does too.

The text is **imported, not written here**, and both halves come from one
object. `TOOL_TEXT[id].summary` is the sentence the Builder shows a person; the
model gets that same sentence plus the usage and the return shape, rendered by
the library. One source, so the two cannot drift, and neither is a paraphrase of
the other.

That is `pydantic-ai-backend` 0.2.28. Before it there was only the full
description, and the Builder rendered all two and a half thousand characters of
`execute` - git safety, package managers, what to do after three failed
attempts - beside a checkbox. The fix people reach for is to write a short label
here instead, which is how a tool's description, the strongest prompt in the
product, gets replaced by a caption for a form. The summary is that label, and
the prompt keeps everything else.

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


def build_workspace(*, include_execute: bool) -> CombinedCapability[Any]:
    """The console tools this agent runs with, and where they work without a runner.

    The tools work in the run's workspace, `ctx.workspace`. The runner opens the
    agent's workspace - a stored document, a container, a cloud sandbox - and
    passes it to the run, which overrides anything here. Where nobody opened
    one - a preview, a test - the run gets an in-memory document that lives
    exactly as long as it does: the honest answer there, rather than an error
    about infrastructure the author did not ask for.

    Args:
        include_execute: Whether the shell is offered at all. Off removes it
            rather than gating it, which is a different decision from "ask
            first" and belongs to whoever configured the agent.
    """
    return CombinedCapability([StateWorkspace(), _console(include_execute=include_execute)])


def _console(*, include_execute: bool) -> ConsoleCapability:
    return ConsoleCapability(
        include_execute=include_execute,
        # So `read_file` on an image returns something a multimodal model can
        # see. Without it an agent cannot look at the chart it just rendered,
        # which is most of the reason to let it render one.
        image_support=True,
        document_support=True,
        # No `descriptions=`: the catalog above shows `TOOL_TEXT[id].summary`
        # and the model reads the rest of the same object, so there is nothing
        # to override and no second copy to drift.
        #
        # `profile="agent"` drops the block written for an agent working in a
        # repository - git, package managers, reading a failed command's output.
        # A workspace here is scratch space deleted with its conversation, so
        # none of it applies, and it was about 240 tokens on every request.
        profile="agent",
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
