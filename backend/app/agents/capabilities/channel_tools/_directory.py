"""What a channel can be asked about, stated once for every platform.

The contract half of "the adapter provides the implementation, the capability
holds the contract". Slack, Telegram and Mattermost all answer *who is in this
channel* and *what is this channel for*, through three different APIs with three
different field names - and if each adapter registered its own tools, the model
would have to know which platform it was standing on before it could ask a
question every platform can answer.

So there is one shape here, and three implementations of it under
`app/services/channels/`. A platform that genuinely cannot answer says so with
:class:`ChannelDirectoryUnsupported`, which the toolset turns into a sentence
the model can act on rather than a failed run: Telegram has no channel search
and gives a bot no way to read history, and pretending otherwise would mean an
agent retrying something that can never work.

Everything here is a **read**, through the bot's own token, in the one channel
the message arrived in. The bot's membership is the permission boundary and the
only one - an agent sees exactly what the bot sees, and there is no call in this
module that widens that.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

CHANNEL_TOOLS_CAPABILITY_ID = "channel_tools"
"""The registry id, held here rather than imported from `__init__`.

The runner assembles this binding for a run and the exposure service validates
against it, so the id is part of the wiring in the same way `SANDBOX_CAPABILITY_ID`
and `DELEGATION_CAPABILITY_ID` are - and an id is a thing other modules name.
"""

CHANNEL_DIRECTORY_RESOURCE = "channel_directory"
"""Where the runner leaves the directory it bound for this run.

Resolved outside the capability because binding one needs the bot row and its
unsealed token, and a capability must never reach the database. Absent on every
surface that is not a channel - the web chat, the API, a schedule - and the
capability then contributes nothing at all, which is the honest answer for an
agent that is not standing in a channel.
"""


class ChannelDirectoryUnsupported(Exception):
    """This platform has no equivalent of what was asked for.

    A permanent no, not a failure: raised by an adapter for an operation its
    platform does not offer a bot. The toolset answers the model with the
    message rather than raising, because a run must not end over a question that
    simply has no answer here.
    """


@dataclass(frozen=True)
class ChannelMember:
    """One person in a channel, as the platform describes them."""

    user_id: str
    username: str | None = None
    display_name: str | None = None
    is_bot: bool = False
    role: str | None = None
    """What the platform calls their standing here - `admin`, `member`.

    `None` where the platform does not say. Carried because on Telegram it is
    the *only* thing a bot can list: `getChatAdministrators` is the whole of
    what a bot may see, so a member list there is a list of administrators and
    has to say so rather than read as everybody.
    """


@dataclass(frozen=True)
class ChannelSummary:
    """A channel as a search result names it."""

    channel_id: str
    name: str
    purpose: str | None = None
    is_private: bool | None = None


@dataclass(frozen=True)
class ChannelDetails:
    """The channel this message arrived in, described."""

    channel_id: str
    name: str
    purpose: str | None = None
    topic: str | None = None
    """The line pinned at the top of the channel - Mattermost's `header`, Slack's
    `topic`. Separate from `purpose`, which says what the channel is *for*;
    teams use the two differently and collapsing them loses whichever they use."""

    is_private: bool | None = None
    member_count: int | None = None


@dataclass(frozen=True)
class ChannelPost:
    """One message already in the channel."""

    author: str
    """What a reader sees - a username where the platform resolves one."""

    text: str
    posted_at: datetime | None = None

    post_id: str | None = None
    """The platform's own id for this message, where the adapter carries one.

    What excludes the current turn from a thread backfill. Comparing text failed
    silently: the adapter strips the bot's mention out of the live message, so the
    same post came back from the history API looking different and the model was
    handed the question twice - once as the prompt and once inside a block
    labelled as other people's words.
    """

    author_id: str | None = None
    """The author as the access policy names them, where the adapter has it.

    `author` is for reading and may be a display name; a whitelist is keyed on
    the platform's user id, so admitting a backfilled speaker needs this one.
    """


class ChannelDirectory(Protocol):
    """One channel, on one platform, reachable with one bot's token.

    Bound to a single channel on purpose: the channel is the one the message
    arrived in, resolved server-side, and the model never names it. An agent
    that could pass a channel id would be an agent that could read any channel
    its bot happens to be in from a conversation in another one.

    :meth:`search` is the one exception and it returns *summaries*, never
    contents - finding that `#billing` exists is not reading it.
    """

    async def details(self) -> ChannelDetails:
        """Name, purpose, topic and size of the channel this run is in."""
        ...

    async def members(self, *, limit: int) -> list[ChannelMember]:
        """Who is in it, up to `limit`."""
        ...

    async def search(self, query: str, *, limit: int) -> list[ChannelSummary]:
        """Channels whose name or purpose matches `query`, within the bot's reach."""
        ...

    async def history(self, *, limit: int) -> list[ChannelPost]:
        """The last `limit` messages, newest last."""
        ...
