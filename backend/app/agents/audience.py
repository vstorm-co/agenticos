"""Who is listening to a run.

Two capabilities need this fact and neither can derive it: memory, which keeps a
note where the conversation keeps it, and conversation search, which will not
read one person's threads aloud to a channel. Both questions are the same one -
*is the person asking the only person who will hear the answer* - and it is a
property of the request rather than of anything stored, so it is resolved once,
server-side, and handed to the run on `AgentDeps`.

An audience has at most one person and at most one room:

- **private** - one person, no room. Web chat and a direct message on a chat
  platform. The person is the only listener.
- **room** - a group chat. The speaker is known, but so is everyone else in the
  channel; the answer is read by all of them.
- **anonymous** - neither. A public widget or an embed, where the run is carried
  by the publisher rather than by whoever is typing (see
  `AuthContext.subject_is_publisher_fallback`), and there is no person to
  attribute anything to. A run started with an API key is the same: the key
  carries its issuer for audit and budget, but a script holding it is not them.

Nothing here is taken from the model. Both fields are derived in
:func:`derive_audience` from the identity the request arrived with, which is what
makes "a run can only reach what it was admitted to" a property of the code
rather than of the prompt.

What each capability *does* with the answer is its own: `app.agents.memory_scope`
turns it into the one memory store a run may touch, and the conversation-search
toolset turns it into a corpus or a refusal.
"""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

__all__ = ["RunAudience", "derive_audience"]


@dataclass(frozen=True)
class RunAudience:
    """Who will hear this run: a person, a room, both, or neither.

    Both `None` is the anonymous audience - an embed or a public widget, where
    there is nobody to attribute anything to and nothing personal may be reached.
    """

    user_id: UUID | None = None
    """The account this run answers for, or `None` when there is no real subject.

    Never the publisher standing in for an unidentified visitor; see
    :func:`derive_audience`.
    """

    room_key: str | None = None
    """The group chat this run is in, as `room:<platform>:<chat_id>`, or `None`.

    Built by `memory_room_key` before it gets here, because deciding that a chat
    has more than one listener needs the platform's own channel type, which only
    the channel layer sees.
    """

    writes_memory: bool = True
    """Whether this run may change the store it reads, not only read it (#2027).

    False for an event trigger acting as its creator: its prompt carries a mail
    or a webhook body nobody vetted, and a note written from it would be read by
    every later conversation as the creator's own.
    """

    searches_conversations: bool = True
    """Whether this run may search the person's past conversations (#2027).

    False for any trigger acting as its creator. Memory and the creator's own
    connections are what a morning report needs; every chat they have had is the
    widest window there is onto them, and no fire needs it.
    """

    browses_signed_in: bool = False
    """Whether the web browser may start signed in with the person's saved sign-ins (#2129).

    True only when the run *is* the person at the keyboard, privately: their chat,
    their direct message, their own schedule acting as them. Not in a room, where
    the answer is read by everyone in it; not through an API key, which is a
    script the person handed a credential to rather than the person; and not for
    an event trigger, whose prompt carries a mail or a webhook body nobody vetted -
    a page that body named would be opened signed in as them. False by default,
    so a run parked before this existed resumes signed out.
    """

    @property
    def private(self) -> bool:
        """Whether the person is the only listener.

        A run with a room is never private, even though it also knows who spoke:
        the answer is posted where the whole channel reads it.
        """
        return self.room_key is None


def derive_audience(
    *,
    user_id: UUID | None,
    subject_is_publisher_fallback: bool,
    fired_as_creator: Literal["schedule", "event"] | None = None,
    room_key: str | None,
    via_api_key: bool = False,
) -> RunAudience:
    """The audience of a run, from the identity the request arrived with.

    The person is resolved **account first**: a real subject keys on their app
    user, whatever surface they arrived on, so web chat and a linked chat account
    reach one store. That is not a lookup - on a channel, a linked
    sender already runs as themselves (`_membership_context` builds the
    `AuthContext` from `ChannelIdentity.user_id`), so the join is in `user_id`
    before this is called. Keying on the chat identity first would have split the
    same human into a browser store and a Slack store and left them reporting that
    the agent forgets them between the two.

    There is no fallback to the chat account itself. It would need a run with a
    chat identity, no room and no real subject - an unlinked direct message, which
    the bot policy refuses before a run starts (#639) - and in a room the person is
    not consulted at all. An unreachable branch is one nobody tests, so it is gone
    rather than kept for a policy that might change (#1470).

    The trap this function exists to avoid is `user_id` on a hosted or embedded
    surface, where it is the *publisher* standing in for an unidentified visitor
    (`publisher_context`). Keying on it there would collapse every visitor onto the
    owner's store, which is a cross-person leak rather than a missing feature - so
    `subject_is_publisher_fallback` separates a real subject from a stand-in.

    A direct message passes `room_key=None` and stays private, which is what makes
    a DM and web chat the same audience for the same person.
    """
    # A key run has no person either: the key holds its issuer's identity for
    # audit, budget and ownership, but whoever holds the key is not that person,
    # and their memory, conversations and signed-in sites are not the key's.
    person = None if subject_is_publisher_fallback or via_api_key else user_id
    return RunAudience(
        user_id=person,
        room_key=room_key,
        writes_memory=fired_as_creator != "event",
        searches_conversations=fired_as_creator is None,
        browses_signed_in=(person is not None and room_key is None and fired_as_creator != "event"),
    )
