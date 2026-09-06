"""What the `conversation_search` capability may find, and who said it.

A run reaches this the way it reaches its memory store: through module-level
functions that open their own short-lived session with `get_db_context`, never on
the session the run is on. Holding that session across a model call is the
idle-in-transaction #12 exists to avoid, and `autoflush` would turn a search into
a flush of whatever the turn had half-written.

**Access is resolved here and nowhere else.** Both entry points build the same
`readable_by` predicate from the same vetted participation set, so what the search
can find and what the read can open cannot disagree - which is the failure mode
that matters, because a search that lists a thread it will then refuse to open has
already told the model the thread exists.

Everything returned is data. How a transcript is written out for a model - the
`USER:` / `AI:` split, who spoke in a channel - belongs to the toolset, which is
the thing that knows it is writing a prompt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
from app.db.session import get_db_context
from app.repositories import agent as agent_repo
from app.repositories import conversation_search as search_repo
from app.repositories import user as user_repo
from app.services.channels import membership as channel_membership

MAX_TURNS_PER_READ = 60
"""How many turns one `read_conversation` call returns.

A window rather than the whole thread: a long channel transcript is tens of
thousands of tokens, and a tool that answers with all of it decides on the model's
behalf that the rest of the conversation does not matter. The caller is told the
total and how to ask for the next window."""


@dataclass(frozen=True)
class FoundConversation:
    """One search result: which thread, how well it matched, and on what."""

    conversation_id: UUID
    title: str | None
    updated_at: datetime
    hits: int
    snippet: str
    speaker_role: str
    speaker_name: str | None


@dataclass(frozen=True)
class TranscriptTurn:
    """One turn, with its speaker already resolved to a name."""

    role: str
    speaker: str | None
    content: str
    at: datetime


@dataclass(frozen=True)
class Transcript:
    """A window of one conversation, and enough to ask for the next."""

    conversation_id: UUID
    title: str | None
    turns: list[TranscriptTurn]
    total: int
    skip: int


async def _readable(
    db: AsyncSession, *, user_id: UUID, organization_id: UUID
) -> ColumnElement[bool]:
    """The access predicate for this person, participation confirmed first.

    The confirmation is a call to the chat platform per (bot, chat, account),
    behind the same one-minute cache the conversation listing uses, and it fails
    closed: a platform that cannot answer means the thread is not readable. That is
    the right way round here too - the alternative is an agent quoting a channel
    somebody was removed from.
    """
    participant_ids = await channel_membership.confirmed_participant_threads(
        db, user_id=user_id, organization_id=organization_id
    )
    return search_repo.readable_by(user_id, participant_ids)


async def search(
    *, query: str, organization_id: UUID, user_id: UUID, limit: int
) -> list[FoundConversation]:
    """The conversations this person may read that match, best first."""
    async with get_db_context() as db:
        readable = await _readable(db, user_id=user_id, organization_id=organization_id)
        hits = await search_repo.search(
            db,
            query=query,
            organization_id=organization_id,
            readable=readable,
            limit=limit,
        )
        return [
            FoundConversation(
                conversation_id=hit.conversation_id,
                title=hit.title,
                updated_at=hit.updated_at,
                hits=hit.hits,
                snippet=hit.snippet,
                speaker_role=hit.speaker_role,
                speaker_name=hit.speaker_name,
            )
            for hit in hits
        ]


async def read(
    *, conversation_id: UUID, organization_id: UUID, user_id: UUID, skip: int
) -> Transcript | None:
    """One window of a conversation, or `None` when this person may not read it.

    `None` covers "no such conversation" and "not yours" alike, deliberately: the
    two are the same answer to whoever asked, and telling them apart would confirm
    that a thread exists in an organization they cannot see into.
    """
    async with get_db_context() as db:
        readable = await _readable(db, user_id=user_id, organization_id=organization_id)
        conversation = await search_repo.readable_conversation(
            db,
            conversation_id=conversation_id,
            organization_id=organization_id,
            readable=readable,
        )
        if conversation is None:
            return None
        window, total = await search_repo.turns(
            db, conversation_id=conversation_id, skip=skip, limit=MAX_TURNS_PER_READ
        )
        agents = await agent_repo.get_many(
            db,
            [turn.agent_id for turn in window if turn.agent_id is not None],
            organization_id=organization_id,
        )
        # The owner names every turn a person typed into the dashboard: those rows
        # carry no chat identity, because there is only ever one human in a thread
        # that came from the console.
        owner = (
            None
            if conversation.user_id is None
            else await user_repo.get_by_id(db, conversation.user_id)
        )
        owner_name = None if owner is None else (owner.full_name or owner.email)
        return Transcript(
            conversation_id=conversation_id,
            title=conversation.title,
            turns=[
                TranscriptTurn(
                    role=turn.role,
                    speaker=_speaker(turn, agents=agents, owner_name=owner_name),
                    content=turn.content,
                    at=turn.created_at,
                )
                for turn in window
            ],
            total=total,
            skip=skip,
        )


def _speaker(
    turn: search_repo.Turn, *, agents: dict[UUID, Agent], owner_name: str | None
) -> str | None:
    """Who said this turn, or `None` when nothing on the row can say.

    A channel account first, because a room has several people in it and the
    thread's owner is not the one who spoke. An assistant turn names the agent
    that produced it - a thread can be answered by more than one, which is why
    `agent_id` sits on the message rather than on the conversation.
    """
    if turn.speaker_name is not None:
        return turn.speaker_name
    if turn.role == "assistant":
        agent = agents.get(turn.agent_id) if turn.agent_id is not None else None
        return None if agent is None else agent.name
    return owner_name
