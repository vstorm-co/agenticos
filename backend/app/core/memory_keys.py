"""The value space of `agent_memory_files.owner_key` - whose memory a note is.

A leaf module on purpose. The same key shapes are needed by the SQLAlchemy model,
by the repository that filters on them, by the run-time audience in
`app.agents.memory_scope` and by the erasure service, and every other home for
them creates an import cycle: `app.db.models.memory` cannot be it, because
importing one model runs `app.db.models.__init__`, which reaches
`services.channels.base` and from there back into the capability registry and
`app.agents.deps`. So the vocabulary lives here, where it imports nothing.

Owners, told apart by prefix:

- `person:<user_id>` - one human being.
- `room:<platform>:<chat_id>` - one group chat.
- `project:<project_id>` and `org:<organization_id>` - the audiences a claim may be
  shared to, and only by an explicit instruction (#2090). Notes (the files and
  their `MEMORY.md`) stay with a person or a room, which is why the column is
  `NOT NULL`; the claims ledger (`memory_claims`) is what reaches the wider scopes.

The organization owner is *not* the store that was removed in #1470: it is never a
union of what individuals told their agents and nothing writes there automatically.

Whose memory a note is, is deliberately not the same question as who may read it
back; that one belongs to the run - `app.agents.audience` says who is listening
and `app.agents.memory_scope` turns that into the one store this run may touch.
"""

from uuid import UUID

__all__ = [
    "INDEX_NAME",
    "ORGANIZATION_PREFIX",
    "PERSON_PREFIX",
    "PROJECT_PREFIX",
    "ROOM_PREFIX",
    "is_person_key",
    "organization_owner_key",
    "person_owner_key",
    "project_owner_key",
    "room_owner_key",
]

INDEX_NAME = "MEMORY.md"
"""The note an agent keeps its index in, and the one spliced into every request.

Here for the same reason the prefixes are: the toolset that reads it, the
capability that splices it and the service that prunes a suppressed note's line
out of it all need the name, and every other home for it is an import cycle -
`app.services.memory` imports the capability package, which imports the toolset,
which imports `app.services.memory` (#1594 review).

It is otherwise an ordinary note: created, read, edited and deleted with the same
tools as any other.
"""

PERSON_PREFIX = "person:"
ROOM_PREFIX = "room:"
PROJECT_PREFIX = "project:"
ORGANIZATION_PREFIX = "org:"


def person_owner_key(user_id: UUID | str) -> str:
    """The store belonging to a person with an account here.

    Keyed on the *user*, not the surface, so the same person reaches one store
    from web chat, the API and a linked chat account - which is the point: a
    memory that does not follow somebody between their browser and their direct
    messages is a memory they will report as broken. It is also what makes
    "forget everything about me" a single key to delete.
    """
    return f"{PERSON_PREFIX}{user_id}"


def room_owner_key(platform: str, chat_id: str) -> str:
    """The store belonging to one group chat.

    `chat_id` is the *channel*, not the thread - `channel_key` has already
    stripped the thread suffix Slack and Mattermost fold in - so a room remembers
    across its threads rather than starting over in each one. The platform is in
    the key because chat ids are only unique within a platform, and one agent can
    be reached from several.
    """
    return f"{ROOM_PREFIX}{platform}:{chat_id}"


def is_person_key(owner_key: str) -> bool:
    """Whether a key names a human being rather than a group chat.

    The one question anything outside this module asks of a stored key, and it is
    asked by erasure: "forget everything about this person" must not reach a room
    a colleague also writes to.
    """
    return owner_key.startswith(PERSON_PREFIX)


def project_owner_key(project_id: UUID | str) -> str:
    """The claims one project's members share, and only they."""
    return f"{PROJECT_PREFIX}{project_id}"


def organization_owner_key(organization_id: UUID | str) -> str:
    """What the whole organization knows.

    Reached only by an explicit instruction from somebody authorized to say it
    (`share_memory`): it is never a union of what individuals told their agents.
    """
    return f"{ORGANIZATION_PREFIX}{organization_id}"
