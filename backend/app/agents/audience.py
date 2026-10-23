"""Who is listening to a run.

Two capabilities need this fact and neither can derive it: memory, which keeps a
note where the conversation keeps it, and conversation search, which will not
read one person's threads aloud to a channel. Both questions are the same one -
*is the person asking the only person who will hear the answer* - and it is a
property of the request rather than of anything stored, so it is resolved once,
server-side, and handed to the run on `AgentDeps`.

An audience has at most one person and at most one room:

- **private** - one person, no room. Web chat, the HTTP API, and a direct message
  on a chat platform. The person is the only listener.
- **room** - a group chat. The speaker is known, but so is everyone else in the
  channel; the answer is read by all of them.
- **anonymous** - neither. A public widget or an embed, where the run is carried
  by the publisher rather than by whoever is typing (see
  `AuthContext.subject_is_publisher_fallback`), and there is no person to
  attribute anything to.

Nothing here is taken from the model. Both fields are derived in
:func:`derive_audience` from the identity the request arrived with, which is what
makes "a run can only reach what it was admitted to" a property of the code
rather than of the prompt.

What each capability *does* with the answer is its own: `app.agents.memory_scope`
turns it into the one memory store a run may touch, and the conversation-search
toolset turns it into a corpus or a refusal.

Beside the audience sits a narrower fact: whether a real member is behind the run
at all - :func:`run_person_for`. The audience answers "who will hear this"; the
run person answers "who answers for what this run does", and a run with no person
is refused the actions that need one. While such a run executes,
:func:`for_no_person` says so to code that cannot be handed the deps - a record
write marks what it wrote as written for nobody.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from app.db.models.agent_run import RunSurface

__all__ = [
    "RunAudience",
    "acting_for_no_person",
    "acting_impersonated",
    "derive_audience",
    "for_no_person",
    "run_impersonated",
    "run_person_for",
]


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
    room_key: str | None,
) -> RunAudience:
    """The audience of a run, from the identity the request arrived with.

    The person is resolved **account first**: a real subject keys on their app
    user, whatever surface they arrived on, so web chat, the HTTP API and a linked
    chat account all reach one store. That is not a lookup - on a channel, a linked
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
    return RunAudience(
        user_id=None if subject_is_publisher_fallback else user_id,
        room_key=room_key,
    )


def run_person_for(
    *,
    user_id: UUID | None,
    subject_is_publisher_fallback: bool,
    surface: RunSurface,
    public_origin: bool,
) -> UUID | None:
    """The member behind a run, or `None` when nobody answers for it.

    Two ways a run has no person, and each is a fact about the request rather than
    about anything stored:

    - `public_origin` - an outsider supplied the input: a webhook, a form, a
      channel message, an email or a repository comment reached a workflow, or a
      delivery fired an event trigger. The run executes as a principal - the
      exposure's or the trigger creator's - but that principal did not write what
      the run acts on, so it is not the person behind it.
    - a publisher standing in for a visitor nobody can name - a widget, an embed,
      an unlinked channel sender. A schedule is the one exception: its fallback
      subject is the creator who set it up, and they answer for it. That is the
      same test as `AgentRun.initiated_by_publisher_fallback`.

    Otherwise the person is `user_id` - the member at the keyboard, a linked
    channel sender, or a workflow run's principal.
    """
    # Imported here: loading the models package reaches the channel layer, whose
    # toolsets import `AgentDeps`, which imports this module.
    from app.db.models.agent_run import RunSurface

    if public_origin:
        return None
    if subject_is_publisher_fallback and surface is not RunSurface.SCHEDULE:
        return None
    return user_id


_for_no_person: ContextVar[bool] = ContextVar("run_for_no_person", default=False)


@contextmanager
def acting_for_no_person(flag: bool) -> Iterator[None]:
    """Say, for the block's duration, whether the run executing has no person.

    Opened by the runner around the agent itself, beside the budget guard and the
    meter, so that code a tool reaches without the deps - a record write - can tell
    what it writes on nobody's behalf. Reset on the way out however the block
    ends, so the flag never outlives the run that set it.
    """
    token = _for_no_person.set(flag)
    try:
        yield
    finally:
        _for_no_person.reset(token)


_impersonated: ContextVar[bool] = ContextVar("run_impersonated", default=False)


@contextmanager
def acting_impersonated(flag: bool) -> Iterator[None]:
    """Say, for the block's duration, whether the run executing started under impersonation.

    Opened beside :func:`acting_for_no_person`, for the same reason: a record a tool
    writes starts the table triggers' runs, which inherit it, and that code is not
    handed the deps.
    """
    token = _impersonated.set(flag)
    try:
        yield
    finally:
        _impersonated.reset(token)


def run_impersonated() -> bool:
    """Whether the run executing now started under impersonation; False outside any run."""
    return _impersonated.get()


def for_no_person() -> bool:
    """Whether the run executing now has no person behind it.

    False outside any run: a write made by the console or a workflow step is
    attributed by its own caller, not by this flag.
    """
    return _for_no_person.get()
