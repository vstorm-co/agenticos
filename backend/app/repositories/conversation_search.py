"""Full-text search over the conversations one person may read.

Separate from `app.repositories.conversation` because it answers a different
question with a different index. That module lists threads and narrows them by
title with `contains_ci`; this one matches *what was said* against
`messages.search_vector` (`0074_message_search_vector`), which is a GIN index and
a `tsquery` rather than a `LIKE` over a column.

Every query here takes `readable` - the predicate saying which conversations the
caller may see - and none of them builds it. Who may read a thread is a decision
with four ways in and one of them costs a call to Slack; it belongs to
`app.services.conversation_search`, which resolves it once and hands it down.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import Any, NamedTuple
from uuid import UUID

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel_identity import ChannelIdentity
from app.db.models.conversation import Conversation, Message
from app.db.models.conversation_share import ConversationShare

SEARCH_CONFIG = "simple"
"""The text search configuration, which must be the one the column was generated
with (`0074_message_search_vector`) - a query tokenised differently from the
document matches nothing, and says so as "no results"."""

_HEADLINE_OPTIONS = (
    "StartSel=**, StopSel=**, MaxFragments=2, FragmentDelimiter= … , MaxWords=18, MinWords=6"
)
"""How `ts_headline` cuts a snippet: up to two fragments of a dozen-odd words each,
with the matched terms wrapped in Markdown emphasis, because what the tool returns
is Markdown."""


def readable_by(user_id: UUID, participant_ids: Collection[UUID]) -> ColumnElement[bool]:
    """Which conversations this person may read, as one predicate.

    Three of the four ways in from `ConversationService._may_read`: the owner,
    anybody it was explicitly shared with, and a participant of a room whose
    membership the *caller* has already confirmed against the platform - vetted
    before it arrives here, exactly as `_reachable_by` takes it, because having
    spoken in a channel is a claim and not access (#641).

    The fourth - a trigger's run-log - is deliberately absent. It is a transcript
    of runs made under somebody else's authority, gated on `runs:view` plus the
    trigger's agent, and an agent searching on a person's behalf carries no
    permission of theirs to check it with.
    """
    ways_in: list[ColumnElement[bool]] = [
        Conversation.user_id == user_id,
        select(ConversationShare.id)
        .select_from(ConversationShare)
        .where(
            ConversationShare.conversation_id == Conversation.id,
            ConversationShare.shared_with == user_id,
        )
        .correlate(Conversation)
        .exists(),
    ]
    if participant_ids:
        ways_in.append(Conversation.id.in_(participant_ids))
    return or_(*ways_in)


_LENGTH_NORMALISATION = 1
"""`ts_rank_cd`'s normalisation flag: divide the rank by `1 + log(document length)`.

Without it - the default, `0` - length is not considered at all, so one mention in
a four-thousand-word paste ranks exactly level with a message whose whole subject
is the thing asked about, and which of the two comes back first is then a tie
broken by something arbitrary. Chat messages vary in length by two orders of
magnitude, which is the case the flag exists for. `1` rather than `2` (divide by
the length outright) because a long message that really is about the term should
lose to a short one, not be buried under every one-line "ok"."""


def _rank(tsquery: Any) -> Any:
    """How well one message matches, length taken into account.

    Written once because the two passes have to agree: the second picks the
    message the first counted as the conversation's best, and a different
    expression there would quote a different message than the one that ranked."""
    return func.ts_rank_cd(Message.search_vector, tsquery, _LENGTH_NORMALISATION)


def _tsquery(query: str) -> Any:
    """The query the model wrote, parsed.

    `websearch_to_tsquery` rather than `plainto_tsquery` because quoted phrases,
    `or` and a leading `-` all mean what somebody typing into a search box expects
    - and rather than `to_tsquery` because nothing the model can write raises a
    syntax error out of it. A query of nothing but stopwords parses to an empty
    tsquery, which matches nothing rather than everything.
    """
    return func.websearch_to_tsquery(SEARCH_CONFIG, query)


class ConversationHit(NamedTuple):
    """One conversation the search matched, and the best thing it matched on."""

    conversation_id: UUID
    title: str | None
    updated_at: datetime
    hits: int
    snippet: str
    speaker_role: str
    speaker_name: str | None


async def search(
    db: AsyncSession,
    *,
    query: str,
    organization_id: UUID,
    readable: ColumnElement[bool],
    limit: int,
) -> list[ConversationHit]:
    """The best-matching conversations, one row each, strongest first.

    Two passes, because `ts_headline` is the expensive half: it re-parses a whole
    message body and cannot be answered from the index, so cutting a snippet for
    every match in a thousand threads to show ten is most of the query's cost. The
    first pass ranks off the GIN index alone; the second cuts one snippet each for
    the few conversations that survived it.

    A conversation is ranked by its *best* message rather than by the sum of them.
    A thread that says the thing once, squarely, is a better answer than one that
    mentions it in passing forty times, and summing rewards length.

    Recency breaks a tie, and then the id breaks that: two conversations matching
    equally well is the ordinary case for a short query, and "the one I was in last
    week" is a better guess than whichever order the planner returned. Without a
    total order the same search returns a different page each time it is run.
    """
    tsquery = _tsquery(query)
    matches = (
        Message.search_vector.op("@@")(tsquery),
        Conversation.organization_id == organization_id,
        readable,
    )
    ranked = (
        select(
            Message.conversation_id,
            func.max(_rank(tsquery)).label("best"),
            func.count().label("hits"),
            func.max(func.coalesce(Conversation.updated_at, Conversation.created_at)).label(
                "last_active"
            ),
        )
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(*matches)
        .group_by(Message.conversation_id)
        .order_by(
            func.max(_rank(tsquery)).desc(),
            func.max(func.coalesce(Conversation.updated_at, Conversation.created_at)).desc(),
            Message.conversation_id,
        )
        .limit(limit)
    )
    rows = (await db.execute(ranked)).all()
    if not rows:
        return []
    hits = {row.conversation_id: row.hits for row in rows}
    order = {row.conversation_id: position for position, row in enumerate(rows)}

    # `DISTINCT ON` is the best row per conversation: the highest-ranked message,
    # and the last-written of those when two rank the same, because the later turn
    # is the one that settled whatever was being discussed.
    snippets = (
        select(
            Message.conversation_id,
            Message.role,
            func.ts_headline(SEARCH_CONFIG, Message.content, tsquery, _HEADLINE_OPTIONS).label(
                "snippet"
            ),
            Conversation.title,
            func.coalesce(Conversation.updated_at, Conversation.created_at).label("updated_at"),
            ChannelIdentity.platform_display_name,
            ChannelIdentity.platform_username,
        )
        .join(Conversation, Conversation.id == Message.conversation_id)
        .outerjoin(ChannelIdentity, ChannelIdentity.id == Message.channel_identity_id)
        .where(*matches, Message.conversation_id.in_(list(hits)))
        .distinct(Message.conversation_id)
        .order_by(
            Message.conversation_id,
            _rank(tsquery).desc(),
            Message.ordinal.desc(),
        )
    )
    found = [
        ConversationHit(
            conversation_id=row.conversation_id,
            title=row.title,
            updated_at=row.updated_at,
            hits=hits[row.conversation_id],
            snippet=row.snippet,
            speaker_role=row.role,
            speaker_name=row.platform_display_name or row.platform_username,
        )
        for row in (await db.execute(snippets)).all()
    ]
    return sorted(found, key=lambda hit: order[hit.conversation_id])


async def readable_conversation(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    organization_id: UUID,
    readable: ColumnElement[bool],
) -> Conversation | None:
    """One conversation, only if this reader may have it.

    The access predicate is in the query rather than applied to what it returns,
    so a conversation id the model repeated from somewhere else - a hallucination,
    an earlier run, another person's transcript - resolves to nothing instead of to
    a row somebody then has to remember to check.
    """
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.organization_id == organization_id,
            readable,
        )
    )
    return result.scalar_one_or_none()


class Turn(NamedTuple):
    """One turn of a transcript, with whoever said it already named."""

    role: str
    content: str
    created_at: datetime
    agent_id: UUID | None
    speaker_name: str | None


async def turns(
    db: AsyncSession, *, conversation_id: UUID, skip: int, limit: int
) -> tuple[list[Turn], int]:
    """A window of one conversation's turns in the order written, and how many there are.

    Ordered by `ordinal`, which is the only column that can say: `created_at` is
    the transaction's start time, so a question and the answer to it carry the same
    timestamp to the microsecond.

    The chat account behind each turn is joined here rather than looked up per row
    - a channel thread is a room of people, and a transcript calling all of them
    "USER" would be unreadable.
    """
    total = await db.scalar(
        select(func.count()).select_from(Message).where(Message.conversation_id == conversation_id)
    )
    rows = await db.execute(
        select(
            Message.role,
            Message.content,
            Message.created_at,
            Message.agent_id,
            ChannelIdentity.platform_display_name,
            ChannelIdentity.platform_username,
        )
        .outerjoin(ChannelIdentity, ChannelIdentity.id == Message.channel_identity_id)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.ordinal)
        .offset(skip)
        .limit(limit)
    )
    window = [
        Turn(
            role=row.role,
            content=row.content,
            created_at=row.created_at,
            agent_id=row.agent_id,
            speaker_name=row.platform_display_name or row.platform_username,
        )
        for row in rows.all()
    ]
    return window, total or 0
