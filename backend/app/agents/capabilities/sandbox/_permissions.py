"""What the workspace refuses outright, before this platform's gate sees it.

Two systems could gate a tool call here and only one of them should. The library
ships a permission checker with `allow` / `deny` / `ask`; this platform has
`ApprovalGate`, which persists a row, mails somebody, parks the run and resumes
it when a human answers. Running both would mean two places deciding, and the
library's `ask` is an in-run `await` that dies with the socket.

So the division is: **the ruleset denies, the platform asks.** A denied
operation has its tools dropped from the toolset entirely, which is stronger
than refusing at call time - the model never sees them. Everything else is
allowed here and left to `approval_required_tools`, which is the half with a
UI and an audit trail.

Nothing below is ever `"ask"`. A shipped preset would be: every one except
`PERMISSIVE_RULESET` defaults an operation to `"ask"`, and an `"ask"` with no
callback is refused or raised depending on `ask_fallback`. `ask_fallback="deny"`
is set anyway, as the backstop for an `"ask"` arriving from somewhere this
module did not put it.
"""

from __future__ import annotations

from pydantic_ai_backends.permissions import (
    SECRETS_PATTERNS,
    SYSTEM_PATTERNS,
    OperationPermissions,
    PermissionRule,
    PermissionRuleset,
)

_OFF_LIMITS = (*SECRETS_PATTERNS, *SYSTEM_PATTERNS)
"""Paths no agent reads or writes, whatever its approval policy says.

The secrets half is the obvious one - an agent that can `read_file` should not
be able to exfiltrate `.env` by asking nicely. The system half matters because a
sandbox is a real filesystem with a real distribution in it: `/etc/passwd` is
readable, uninteresting, and a waste of a turn, while `/usr/**` is where a
confused agent goes looking for the file it just wrote.
"""


def _deny_off_limits() -> list[PermissionRule]:
    return [
        PermissionRule(
            pattern=pattern,
            action="deny",
            description="Outside the workspace, or a credential",
        )
        for pattern in _OFF_LIMITS
    ]


def workspace_ruleset() -> PermissionRuleset:
    """Allow the workspace, deny what is not it.

    Built fresh per call rather than shared as a module constant: a
    `PermissionRuleset` is handed to a capability that lives for one run, and a
    mutable default shared across every agent in the deployment is the kind of
    thing that is fine until something writes to it.
    """
    off_limits = _deny_off_limits()
    return PermissionRuleset(
        default="allow",
        read=OperationPermissions(default="allow", rules=off_limits),
        write=OperationPermissions(default="allow", rules=off_limits),
        edit=OperationPermissions(default="allow", rules=off_limits),
        # Commands are not filtered by pattern here. A shell is not a path, an
        # allowlist of command strings is defeated by `sh -c`, and the isolation
        # that makes execution safe is the container's - not a regular
        # expression. Whether the agent may run one at all is the approval
        # gate's decision, and whether it can reach anything is `network_mode`.
        execute=OperationPermissions(default="allow"),
        glob=OperationPermissions(default="allow"),
        grep=OperationPermissions(default="allow"),
        ls=OperationPermissions(default="allow"),
    )
