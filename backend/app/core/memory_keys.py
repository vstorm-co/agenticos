"""The value space of `agent_memory_*.owner_key` - whose memory a row is.

A leaf module on purpose. The same three key shapes are needed by the SQLAlchemy
models, by the repository that filters on them, by the run-time audience in
`app.agents.memory_scope` and by the operator service, and every other home for
them creates an import cycle: `app.db.models.memory` cannot be it, because
importing one model runs `app.db.models.__init__`, which reaches
`services.channels.base` and from there back into the capability registry and
`app.agents.deps`. So the vocabulary lives here, where it imports nothing.

Three owners, one column, told apart by prefix:

- `NULL` - the organization. One store per (organization, agent).
- `person:<user_id>`, or `person:chan:<identity_id>` for a chat account no app
  user is linked to - one human being.
- `room:<platform>:<chat_id>` - one group chat.

Whose memory a row is, is deliberately not the same question as who may read it
back; that one belongs to the run and lives in `app.agents.memory_scope`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, get_args
from uuid import UUID

__all__ = [
    "PERSON_PREFIX",
    "ROOM_PREFIX",
    "MemoryOwnerKind",
    "OwnerFilter",
    "channel_person_owner_key",
    "owner_kind",
    "parse_owner_selector",
    "person_owner_key",
    "room_owner_key",
]

OwnerFilter = Literal["all", "org", "person", "room"]
"""Which owners an operator listing spans. `all` is every store at once."""

_OWNER_FILTERS: frozenset[str] = frozenset(get_args(OwnerFilter))

PERSON_PREFIX = "person:"
ROOM_PREFIX = "room:"


class MemoryOwnerKind(StrEnum):
    """Whose memory a row is - the three owners `owner_key` encodes."""

    ORG = "org"
    """The organization. `owner_key IS NULL`; readable in every run."""

    PERSON = "person"
    """One human being. Readable only where they are the sole listener."""

    ROOM = "room"
    """One group chat. Readable by anyone in that room."""


def person_owner_key(user_id: UUID | str) -> str:
    """The store belonging to a person with an account here.

    Keyed on the *user*, not the surface, so the same person reaches one store
    from web chat, the API and a linked chat account - which is the point: a
    memory that does not follow somebody between their browser and their direct
    messages is a memory they will report as broken.
    """
    return f"{PERSON_PREFIX}{user_id}"


def channel_person_owner_key(channel_identity_id: UUID) -> str:
    """The store belonging to a chat account no app user is linked to.

    Still a person - just one we can only name by the account they wrote from.
    Stable and isolated like any other person key; it stops being used the moment
    the account is linked, at which point that person's web and chat runs converge
    on :func:`person_owner_key` and this store is left behind rather than merged
    (merging two stores is an operator's decision, not a login's).
    """
    return f"{PERSON_PREFIX}chan:{channel_identity_id}"


def room_owner_key(platform: str, chat_id: str) -> str:
    """The store belonging to one group chat.

    `chat_id` is the *channel*, not the thread - `channel_key` has already
    stripped the thread suffix Slack and Mattermost fold in - so a room remembers
    across its threads rather than starting over in each one. The platform is in
    the key because chat ids are only unique within a platform, and one agent can
    be reached from several.
    """
    return f"{ROOM_PREFIX}{platform}:{chat_id}"


def owner_kind(owner_key: str | None) -> MemoryOwnerKind:
    """Whose store a key names.

    Total by construction: `NULL` is the organization and a `room:` prefix is a
    room, so anything else is a person - including the `person:chan:` form. A key
    that matched nothing would have to be reported somewhere, and there is no
    honest answer for a row whose owner cannot be determined, so the prefixes are
    written by the three builders above and read only here.
    """
    if owner_key is None:
        return MemoryOwnerKind.ORG
    if owner_key.startswith(ROOM_PREFIX):
        return MemoryOwnerKind.ROOM
    return MemoryOwnerKind.PERSON


def parse_owner_selector(value: str) -> tuple[str | None, OwnerFilter | None]:
    """Split the console's one `owner` query parameter into the two the service takes.

    The parameter is one string because a filter strip is one control, but the
    service takes a *kind* and a *key* separately and they are exclusive: passing
    a key as a kind would silently list every person's store to somebody auditing
    one, which is the direction that leaks. So the two shapes are told apart here,
    once, rather than at each of the two listing routes.
    """
    if value in _OWNER_FILTERS:
        # A runtime `in` does not narrow a `Literal`, and the set is derived from
        # that very `Literal`, so the check and the type cannot drift apart.
        return None, value  # ty: ignore[invalid-return-type]
    return value, None
