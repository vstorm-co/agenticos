"""Who is listening to a run, and therefore which memory it may read and write.

A memory row records *whose* it is (`owner_key`, in `app.db.models.memory`). A
run records *who will hear the answer*, and that is this module. Keeping the two
apart is the whole of the memory access model, because collapsing them is what
let a note taken in a private conversation be read back aloud in a group channel:
"this person's store" and "somewhere only this person is listening" are not the
same fact, and one column cannot hold both (#788).

An audience has at most one person and at most one room:

- **private** - one person, no room. Web chat, the HTTP API, and a direct message
  on a chat platform. The person is the only listener.
- **room** - a group chat. The speaker is known, but so is everyone else in the
  channel; the answer is read by all of them.
- **anonymous** - neither. A public widget or an embed, where the run is carried
  by the publisher rather than by whoever is typing (see
  `AuthContext.subject_is_publisher_fallback`), and there is no person to
  attribute anything to.

Two rules follow, and every refusal in the toolset is one of them:

**Reading.** A row is readable only when everyone who hears the run was already
entitled to it. The organization store is readable everywhere; a room's store
only in that room; a person's store only where that person is the sole listener.
A private run therefore does *not* read the rooms its person belongs to - not
because they are not entitled, but because proving it means asking the platform
for the membership of every room on every request, which is not a question a
standing brief can afford. That is a deliberate limit, not an oversight.

**Writing.** Writing *narrower* than the audience is always safe - the audience
already heard it, and a narrower store is read by fewer people. Writing *wider*
is the one dangerous direction, and it is the only one behind a lever
(`allow_agent_shared_writes`). This is why the default scope is the audience's
own: it can leak nothing by construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.core.memory_keys import channel_person_owner_key, person_owner_key

__all__ = [
    "MemoryAudience",
    "MemoryScope",
    "derive_audience",
]

MemoryScope = Literal["personal", "room", "shared"]
"""Which store a write targets. The model picks the store; the server picks the key."""


@dataclass(frozen=True)
class MemoryAudience:
    """Who will hear this run, as the two owner keys it admits.

    Both `None` is the anonymous audience: the run reads the organization store
    and can write nothing but it. Neither key is ever taken from the model - they
    are derived in :func:`derive_audience` from the request's own identity - which
    is what makes "a run can only reach stores it was admitted to" a property of
    the code rather than of the prompt.
    """

    person_key: str | None = None
    room_key: str | None = None

    @property
    def private(self) -> bool:
        """Whether the person is the only listener.

        A run with a room is never private, even though it also knows who spoke:
        the answer is posted where the whole channel reads it.
        """
        return self.room_key is None

    def read_keys(self, *, allow_personal: bool) -> tuple[str | None, ...]:
        """The owner keys this run may read, most specific first.

        Ordered because a file name can exist in more than one store, and
        `read_memory` has to resolve the clash the way the reader expects: the
        person's own copy before the room's, the room's before the
        organization's. The organization store is always last and always present.

        `allow_personal` off (the operator's compliance lever) drops the person
        arm, which is the same shape as a run that simply has no person.
        """
        keys: list[str | None] = []
        if allow_personal and self.private and self.person_key is not None:
            keys.append(self.person_key)
        if self.room_key is not None:
            keys.append(self.room_key)
        keys.append(None)
        return tuple(keys)

    def default_scope(self) -> MemoryScope:
        """The store a write goes to when the model does not choose one.

        The audience's own, which is the one choice that can leak nothing: whoever
        would read it back has already heard the conversation it came from. In a
        room that is the room; otherwise the person, falling back to the
        organization only when there is nobody to attribute it to.
        """
        if self.room_key is not None:
            return "room"
        return "personal" if self.person_key is not None else "shared"

    def write_key(self, scope: MemoryScope, *, allow_personal: bool) -> str | Literal[False] | None:
        """The owner key a write to `scope` lands on, or `False` when it cannot.

        `False` rather than `None` for a refusal, because `None` is a real answer
        here - it is the organization store. A refusal is never quietly redirected
        to another store: sending a personal note to the organization because there
        was no person is exactly the leak this module exists to stop, so the caller
        turns `False` into a refusal the model reads.
        """
        if scope == "shared":
            return None
        if scope == "room":
            return self.room_key if self.room_key is not None else False
        if not allow_personal or self.person_key is None:
            return False
        return self.person_key


def derive_audience(
    *,
    channel_identity_id: UUID | None,
    user_id: str | None,
    subject_is_publisher_fallback: bool,
    room_key: str | None,
) -> MemoryAudience:
    """The audience of a run, from the identity the request arrived with.

    The person is resolved **account first**: a real subject keys on their app
    user, whatever surface they arrived on, so web chat, the HTTP API and a linked
    chat account all reach one store. That is not a lookup - on a channel, a linked
    sender already runs as themselves (`_membership_context` builds the
    `AuthContext` from `ChannelIdentity.user_id`), so the join is in `user_id`
    before this is called. Keying on the chat identity first would have split the
    same human into a browser store and a Slack store and left them reporting that
    the agent forgets them between the two.

    A chat account with no app user has no real subject to key on - the run is
    carried by the publisher - so it keys on the identity instead: still one
    person, just one we can only name by the account they wrote from.

    The trap this function exists to avoid is `user_id` on a hosted or embedded
    surface, where it is the *publisher* standing in for an unidentified visitor
    (`publisher_context`). Keying on it there would collapse every visitor onto the
    owner's store, which is a cross-person leak rather than a missing feature - so
    `subject_is_publisher_fallback` is what separates a real subject from a stand-in,
    and where a stand-in is all there is, an unlinked chat identity is a better
    person than the owner and no person at all is better than either.

    `room_key` arrives already built (`room_owner_key`), because deciding that a
    chat has more than one listener needs the platform's own channel type, which
    only the channel layer sees. A direct message passes `None` and stays private,
    which is what makes a DM and web chat the same audience for the same person.
    """
    if user_id is not None and not subject_is_publisher_fallback:
        person_key: str | None = person_owner_key(user_id)
    elif channel_identity_id is not None:
        person_key = channel_person_owner_key(channel_identity_id)
    else:
        person_key = None
    return MemoryAudience(person_key=person_key, room_key=room_key)
