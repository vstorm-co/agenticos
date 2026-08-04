"""What the workspace refuses outright, before this platform's gate sees it.

Two systems could gate a tool call here and only one of them should. The library
ships a permission checker with `allow` / `deny` / `ask`; this platform has
`ApprovalGate`, which persists a row, mails somebody, parks the run and resumes
it when a human answers. Running both would mean two places deciding, and the
library's `ask` is an in-run `await` that dies with the socket.

So the division is: **the ruleset denies, the platform asks.** A denied
*operation* has its tools dropped from the toolset entirely, which is stronger
than refusing at call time - the model never sees them. Everything else is
allowed here and left to `approval_required_tools`, which is the half with a
UI and an audit trail.

A denied **path** is a different mechanism, and handing the ruleset to
`ConsoleCapability` is not it. `permissions=` reaches exactly two things in the
library's console toolset: `requires_approval`, for the write and execute
approval flags, and `_denied_tools`, which unregisters a tool when
`is_denied(ruleset, operation)` - and that is the whole of `is_denied`::

    return _default_action(ruleset, operation) == "deny"

It reads an operation's *default action*. Nothing in the toolset reads
`OperationPermissions.rules`, so the per-path patterns below were decoration:
with every operation `default="allow"`, an agent read `/etc/passwd`, `**/.env`
and `**/*.pem` as freely as its own scratch files. `GuardedBackend` is what
makes them mean something, by asking the checker on the way past.

Nothing below is ever `"ask"`. A shipped preset would be: every one except
`PERMISSIVE_RULESET` defaults an operation to `"ask"`, and an `"ask"` with no
callback is refused or raised depending on `ask_fallback`. `ask_fallback="deny"`
is set anyway, as the backstop for an `"ask"` arriving from somewhere this
module did not put it.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai_backends import (
    AsyncBackendProtocol,
    BackendProtocol,
    EditResult,
    FileInfo,
    GrepMatch,
    WriteResult,
    ensure_async,
)
from pydantic_ai_backends.permissions import (
    SECRETS_PATTERNS,
    SYSTEM_PATTERNS,
    OperationPermissions,
    PermissionChecker,
    PermissionOperation,
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


class GuardedBackend:
    """A workspace that refuses an off-limits path before the real one sees it.

    The ruleset above describes what an agent may touch; this is what enforces
    it. Wrapping the backend rather than filtering tool arguments is what makes
    the guard total: every tool in the library's console toolset reaches the
    filesystem through these eight methods, so a tool added there in a later
    release is guarded on the day it arrives rather than the day somebody
    remembers to list it.

    **Content and mutation are guarded; existence is not.** `read`, `read_bytes`
    and `grep_raw` are the three ways bytes come *out* of a file, and `write` and
    `edit` the two that change one - those ask the checker. `exists`, `ls_info`
    and `glob_info` answer about names, which is a weaker claim than the contents
    and not what `_OFF_LIMITS` is written to protect; they delegate untouched, so
    `ls /etc` still says what is there and reading any of it still refuses.

    `grep_raw` is filtered rather than refused, because it takes a tree and not a
    path: a pattern over `/` legitimately covers the workspace *and* whatever
    else the container mounts, and the honest answer is the matches the agent may
    have rather than an error about the ones it may not. Filtering the results is
    also the only place this can happen - the walk is inside the backend.

    A refusal is a value where the protocol has one and an exception where it does
    not. `write` and `edit` return an error result, which is what the model reads
    and can act on; `read` and `read_bytes` return `str` and `bytes`, so there is
    no error to return and the library's own `_degrade_on_error` turns the raise
    into the same readable `Error: ...` the model would have got either way.
    """

    def __init__(
        self, backend: BackendProtocol | AsyncBackendProtocol, ruleset: PermissionRuleset
    ) -> None:
        # `ensure_async` first, and it costs nothing that was not already paid:
        # the console toolset calls it on every single tool call anyway. Doing it
        # here is what lets one guard cover both shapes `build_workspace` accepts -
        # a sync guard over an async backend would have returned un-awaited
        # coroutines, which is a bug the type checker is right to refuse.
        self._backend = ensure_async(backend)
        # Kept as well, because the adapter only proxies the eight protocol
        # methods and `execute`. `stop` on a container and `files` on a stored
        # workspace are reached through `__getattr__` below.
        self._raw = backend
        self._checker = PermissionChecker(ruleset)

    def _denied(self, operation: PermissionOperation, path: str) -> bool:
        # `check_sync`, not `check`: it resolves the action without touching a
        # callback, which is what this needs - there is no callback and `"ask"` is
        # never in the ruleset. It is also cheap and synchronous, so a refused path
        # never costs the thread hop the real call would have.
        return self._checker.check_sync(operation, path) == "deny"

    @staticmethod
    def _refusal(verb: str, path: str) -> str:
        """What the model is told. A past participle rather than the operation
        name, because this is a sentence and `write` is not the word for it."""
        return (
            f"Permission denied: '{path}' is outside the workspace or holds a "
            f"credential, so it cannot be {verb}. Work inside the workspace."
        )

    async def read(self, path: str, offset: int = 0, limit: int = 2000) -> str:
        if self._denied("read", path):
            raise PermissionError(self._refusal("read", path))
        return await self._backend.read(path, offset, limit)

    async def read_bytes(self, path: str) -> bytes:
        if self._denied("read", path):
            raise PermissionError(self._refusal("read", path))
        return await self._backend.read_bytes(path)

    async def write(self, path: str, content: str | bytes) -> WriteResult:
        if self._denied("write", path):
            return WriteResult(error=self._refusal("written", path))
        return await self._backend.write(path, content)

    async def edit(
        self, path: str, old_string: str, new_string: str, replace_all: bool = False
    ) -> EditResult:
        if self._denied("edit", path):
            return EditResult(error=self._refusal("edited", path))
        return await self._backend.edit(path, old_string, new_string, replace_all)

    async def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        ignore_hidden: bool = True,
    ) -> list[GrepMatch] | str:
        found = await self._backend.grep_raw(pattern, path, glob, ignore_hidden)
        # A string is the backend's own error or "no matches", not a result set.
        if isinstance(found, str):
            return found
        return [match for match in found if not self._denied("read", match["path"])]

    async def exists(self, path: str) -> bool:
        return await self._backend.exists(path)

    async def ls_info(self, path: str) -> list[FileInfo]:
        return await self._backend.ls_info(path)

    async def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        return await self._backend.glob_info(pattern, path)

    def __getattr__(self, name: str) -> Any:
        """Everything the protocol does not name, straight through.

        A workspace is more than the protocol: `RemoteSandbox` has `execute`,
        `stop` and `start`, and `CappedStateBackend` has `files`, which the flush
        reads. Delegating by name rather than listing them is what keeps this
        wrapper from quietly removing a capability the way an explicit list would -
        and the guarded methods are defined above, so they are found first.

        The adapter is asked before the backend, so anything it *does* carry comes
        back awaitable. `execute` is the one that matters: the console toolset
        awaits it, and handing back the synchronous original would raise on a
        `str` that cannot be awaited.

        `Any` because the return type genuinely varies with the attribute; the
        wrapped backend's own annotations are what a caller sees.
        """
        if hasattr(self._backend, name):
            return getattr(self._backend, name)
        return getattr(self._raw, name)

    def __repr__(self) -> str:
        return f"<GuardedBackend({self._backend!r})>"
