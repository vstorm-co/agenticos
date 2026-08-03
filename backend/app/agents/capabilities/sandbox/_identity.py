"""Who a workspace belongs to, and the key that follows from it.

`session_scope` is not a technical setting with four values; it is the answer to
"who shares files with whom", and the key is where that answer becomes
mechanical. Deriving it here - once, from facts the runner resolved - is what
stops two surfaces computing it differently and one of them handing a Slack
channel somebody else's workspace.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

SessionScope = Literal["run", "conversation", "channel", "user", "agent"]
"""Who shares a workspace.

`conversation` and `channel` are both here because a chat platform makes them
different things. `SlackAdapter` folds `thread_ts` into `platform_chat_id`, so a
Slack thread *is* a conversation - which means `conversation` scope on Slack gives
one workspace per thread, and a channel with fifty threads gives fifty of them.
Under a container backend that is fifty containers, `max_sessions` exhausted, and
a `429` for the fifty-first person to reply.

`channel` keys on the chat with the thread stripped, so threads in one channel
share. A direct message has its own chat id either way, so "each person gets
their own in DMs" needs no extra rule.
"""

BackendKind = Literal["state", "service"]

_BACKEND_LETTER: dict[str, str] = {"state": "d", "service": "x"}
"""One letter per backend, and neither of them is the first letter of its name.

`backend[0]` was `s` for both `state` and `service`, which silently defeated the
one thing folding the backend into the key is for: switching a live conversation
from a stored document to a container reattached to the old key, and the two are
not the same shape of thing. `d` for the document, `x` for the executor.
"""

_SCOPE_LETTER: dict[str, str] = {
    "run": "r",
    "conversation": "c",
    "channel": "h",
    "user": "u",
    "agent": "a",
}
"""One letter per scope, written out rather than taken from the name.

`scope[0]` gave `conversation` and `channel` the same letter, which defeated the
only thing the prefix is for: telling a reader - and a key - that two workspaces
were built under different policies. The subjects differ anyway, so nothing
collided; a prefix that cannot distinguish what it exists to distinguish is still
worth fixing before it does.
"""

MAX_SESSION_ID = 64
"""`sandboxd` constrains ids to `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`.

Worth stating as a constant because the obvious key - two hyphen-stripped UUIDs
and a separator - is 65 characters, one over, and would be rejected on the first
tool call rather than when the key was built.
"""


class WorkspaceScopeUnavailable(Exception):
    """This run has nothing to key the chosen scope on.

    Raised rather than quietly falling back to a broader scope: `user` scope on
    a surface with no user would otherwise merge strangers' files into one
    workspace, and the fallback would be invisible.
    """


@dataclass(frozen=True)
class WorkspaceIdentity:
    """The facts a scope key is built from, resolved server-side.

    Everything here comes from the request and the run row. None of it is
    model-controlled, which is the point: the model asks to read a file, never
    to read *somebody else's* file.
    """

    organization_id: UUID
    agent_id: UUID
    run_id: UUID
    conversation_id: UUID | None = None
    user_id: str | None = None
    channel_key: str | None = None
    """The chat this run arrived in, with any thread stripped.

    Set only on a messaging channel; `None` in web chat, where there is no
    channel above the conversation. It is the platform's own id rather than a row
    of ours because it has to be stable across the threads inside it, and a
    `ChannelSession` is created per thread.
    """


def scope_key(identity: WorkspaceIdentity, scope: SessionScope, backend: BackendKind) -> str:
    """The workspace this run attaches to.

    The organization prefix is for reading a dashboard, **not** for isolation -
    isolation comes from the keys being `uuid4`, which are unguessable and
    globally unique. Worth saying plainly, because a reader who believes the
    prefix is the security boundary will either shorten it carelessly or refuse
    to touch it for the wrong reason. Tenant isolation is enforced by the
    organization check on every row that produces these ids, and by the
    `tenant` label the service counts against.

    The backend kind is folded in so that changing `state` to a container on a
    live conversation opens a new workspace instead of reattaching to one of a
    different shape - a `StateBackend` document and a container's volume are not
    the same thing wearing different names.

    Raises:
        WorkspaceScopeUnavailable: If the scope needs an id this run does not
            have - `conversation` on a stateless API call, `user` on an
            anonymous surface.
    """
    subject = _subject(identity, scope)
    key = f"{_BACKEND_LETTER[backend]}{_SCOPE_LETTER[scope]}-{identity.organization_id.hex[:8]}-{subject}"
    # 1 + 1 + 1 + 8 + 1 + 32 = 44 for a UUID subject; a channel identity string
    # can be longer, so the bound is enforced rather than reasoned about.
    return key[:MAX_SESSION_ID]


def _subject(identity: WorkspaceIdentity, scope: SessionScope) -> str:
    if scope == "run":
        return identity.run_id.hex
    if scope == "agent":
        return identity.agent_id.hex
    if scope == "conversation":
        if identity.conversation_id is None:
            raise WorkspaceScopeUnavailable(
                "This run has no conversation, so a conversation-scoped workspace "
                "has nothing to attach to."
            )
        return identity.conversation_id.hex
    if scope == "channel":
        if identity.channel_key is None:
            raise WorkspaceScopeUnavailable(
                "This run did not arrive on a messaging channel, so there is no "
                "channel to share a workspace across. Use 'conversation' or 'user'."
            )
        # Per agent as well as per channel: two agents in one Slack channel are
        # two different jobs, and one reading the other's files is not something
        # anybody asked for by putting both in the same room.
        return f"{identity.agent_id.hex[:8]}{_digest(identity.channel_key)}"
    if identity.user_id is None:
        raise WorkspaceScopeUnavailable(
            "This run has no signed-in user, so a user-scoped workspace has nothing to attach to."
        )
    # Per user *per agent*: one person's workspace in the support agent is not
    # their workspace in the finance agent, and merging them would let an agent
    # read files gathered for another one.
    return f"{identity.agent_id.hex[:8]}{_digest(identity.user_id)}"


def _digest(user_id: str) -> str:
    """A user id `sandboxd` will accept as part of a session id.

    Hashed rather than sanitised. Not every surface's user id is a UUID - a
    Slack member id, a Telegram number - and dropping the characters the id
    pattern forbids maps `a.b` and `ab` onto one workspace, which is one user
    reading another's files. A digest is fixed-length, inside the alphabet, and
    cannot collide by construction.

    Unreadable in a dashboard on purpose: the row in `agent_workspaces` is what
    says whose workspace this is, and it can say so without putting an
    identifier in a string that also names a container.
    """
    return hashlib.sha256(user_id.encode()).hexdigest()[:24]
