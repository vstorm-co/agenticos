"""A person approves a write to a mount whose author asked for one.

Approval in this platform is per tool call (`app.agents.capabilities.approval`):
the gate asks before a tool runs, a person answers in the shared queue, and a
parked call resumes once they have. A terminal needs the question narrower than
the tool. `mirage_execute ls` and `mirage_execute rm /drive/report.pdf` are the
same tool, and an author who mounts a Drive folder writable "but ask me first"
means the second and not the first.

So the question is decided by **what the call would write**, and put to the gate
before the call runs:

- `mirage_write_file` and `mirage_edit_file` write the `path` they are given.
- `mirage_execute` runs a shell line, and Mirage itself says what that line
  would do: `explain` is a dry run of the same policies the line will meet,
  `WriteApproval` among them, which answers `Ask` for a write into a gated
  mount.

The answer is the gate's: granted runs the call, rejected returns the refusal
the gate would, and nobody-yet raises `ApprovalRequired`, which parks the run
exactly as a gated tool does. On resume the same call asks again under the same
id and the gate answers from what was recorded - asking every time rather than
trusting `ctx.tool_call_approved` is deliberate, since the runner replays a
*rejected* call as approved too.

`ask` - Mirage's own `on_ask` - is the backstop rather than the mechanism. Mirage
catches an exception raised there and fails the line, so a question cannot be
parked from inside it. It allows a gated write only during a call the gate
approved, and refuses one any dry run missed: a path built at run time
(`echo x > $TARGET`), which `explain` does not expand.
"""

import contextvars
import dataclasses
import posixpath
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from typing import Any

from mirage import Ask, Policy, Workspace
from mirage.policy.types import (
    CommandContext,
    Decision,
    Outcome,
    ShellExplanation,
    VfsContext,
    WordKind,
)
from pydantic_ai import ApprovalRequired, RunContext

from app.agents.approval import ApprovalGranted, ApprovalPending, ApprovalRequest, refusal
from app.agents.deps import AgentDeps

CAPABILITY_ID = "mirage"

_FILE_WRITERS = frozenset({"write_file", "edit_file"})

_APPROVED: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "mirage_write_approved", default=False
)


class WriteApproval(Policy):
    """`Ask` for a write into one of `gated`, the mounts an author wants asked about.

    `gated` holds mount prefixes as Mirage spells them, with a trailing slash.
    """

    def __init__(self, gated: frozenset[str]) -> None:
        self.gated = gated

    async def pre_command(self, ctx: CommandContext) -> Ask | None:
        # A redirect is a write the shell does, not the command, so `echo x >
        # /drive/a` carries `write=False`; its target is still among `paths`.
        redirected = {word.text for word in ctx.words if word.kind == WordKind.REDIRECT}
        for path in ctx.paths:
            if path.directory in self.gated and (ctx.write or path.virtual in redirected):
                return Ask(reason=_reason(path.directory))
        return None

    async def pre_vfs(self, ctx: VfsContext) -> Ask | None:
        if ctx.write and ctx.prefix in self.gated:
            return Ask(reason=_reason(ctx.prefix))
        return None


def _reason(prefix: str) -> str:
    return f"writing to {prefix} needs a person to approve it"


async def needs_approval(
    workspace: Workspace, gated: frozenset[str], tool: str, args: Mapping[str, Any]
) -> bool:
    """Whether this call, as typed, writes into a gated mount."""
    if not gated:
        return False
    if tool in _FILE_WRITERS:
        path = posixpath.normpath(posixpath.join("/", str(args.get("path", ""))))
        return any(f"{path}/".startswith(prefix) for prefix in gated)
    if tool == "execute":
        return _asks(await workspace.explain(str(args.get("command", ""))))
    return False


def _asks(explanation: ShellExplanation) -> bool:
    if any(isinstance(answer, Ask) for answer in explanation.answers):
        return True
    stack: list[Any] = [explanation.node]
    while stack:
        node = stack.pop()
        if any(isinstance(answer, Ask) for answer in getattr(node, "answers", ())):
            return True
        stack.extend(getattr(node, "children", ()))
    return False


async def approve(ctx: RunContext[AgentDeps], tool_name: str, args: dict[str, Any]) -> str | None:
    """Put the call to the gate. `None` when it may go on; otherwise what the model reads.

    Raises:
        ApprovalRequired: Nobody has answered yet; the run parks the call.
    """
    request = ctx.deps.request_approval
    if request is None:
        return refusal(tool_name, "this surface cannot ask anyone to approve it")
    verdict = await request(
        ApprovalRequest(
            capability_id=CAPABILITY_ID,
            tool_name=tool_name,
            tool_call_id=ctx.tool_call_id or "",
            tool_args=args,
        )
    )
    if isinstance(verdict, ApprovalPending):
        raise ApprovalRequired()
    if isinstance(verdict, ApprovalGranted):
        if verdict.tool_args != args:
            return refusal(tool_name, "it was approved with different arguments; call it again")
        return None
    return refusal(tool_name, verdict.note or "a reviewer rejected it")


@contextmanager
def approved_writes(approved: bool) -> Generator[None]:
    """Whether gated writes in the call running inside this block were approved."""
    token = _APPROVED.set(approved)
    try:
        yield
    finally:
        _APPROVED.reset(token)


async def ask(decision: Decision) -> Decision:
    """Mirage's question about a gated write, answered from the call's approval."""
    if _APPROVED.get():
        return dataclasses.replace(decision, outcome=Outcome.ALLOW)
    return dataclasses.replace(
        decision,
        outcome=Outcome.DENY,
        note="it needs a person's approval; write to the path spelled out so it can be asked for",
    )
