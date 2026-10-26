"""What a new connection of a call starts from (#54, amendment 9).

Text transcripts, never audio: a nine-minute call is about 2k text tokens, under
a cent and partly prompt-cached, so a reconnect does not re-bill the call. Only
what the caller may read is seeded - the conversation passed the ownership check
before this is reached - because seeded history is visible to the browser peer.

When the transcript would fill more than half the model's context window, the
older turns become a short summary written by the agent's own chat model and
billed to the run, and the recent turns follow verbatim.
"""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.messages import ModelMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import (
    can_afford_ambient_call,
    guarded_by,
    metered_by,
    record_ambient_usage,
)
from app.agents.observability import inherited_instrumentation
from app.repositories import conversation_repo
from app.services.message_history import HistoryMessage, build_message_history

if TYPE_CHECKING:
    from app.services.agent_runner import PreparedRun

SEED_FRACTION = 0.5
RECENT_TURNS_KEPT = 12
CHARS_PER_TOKEN = 4
HISTORY_LIMIT = 200

Summarise = Callable[[str], Awaitable[str]]

_SUMMARY_PROMPT = (
    "Summarise this conversation for the assistant who continues it by voice. Keep names, "
    "amounts, dates, decisions and open questions. At most 150 words, plain sentences."
)


async def seed_history(
    db: AsyncSession, *, conversation_id: UUID, context_window: int, summarise: Summarise
) -> list[ModelMessage]:
    """The conversation's typed and spoken turns as history for a new session.

    Verbatim while they fit half the model's context window; past that, a
    summary of the older turns followed by the recent ones.
    """
    rows = await conversation_repo.get_recent_messages(db, conversation_id, limit=HISTORY_LIMIT)
    history: list[HistoryMessage] = [
        {"role": row.role, "content": row.content}
        for row in rows
        if row.role in ("user", "assistant") and row.content.strip()
    ]
    budget = int(context_window * SEED_FRACTION) * CHARS_PER_TOKEN
    if sum(len(turn["content"]) for turn in history) <= budget:
        return build_message_history(history)
    recent = history[-RECENT_TURNS_KEPT:]
    while recent and sum(len(turn["content"]) for turn in recent) > budget // 2:
        recent = recent[1:]
    older = history[: len(history) - len(recent)]
    transcript = "\n".join(f"{turn['role']}: {turn['content']}" for turn in older)
    summary = await summarise(transcript[-budget:])
    seeded: list[HistoryMessage] = (
        [{"role": "user", "content": f"(Summary of the conversation so far) {summary}"}]
        if summary
        else []
    )
    return build_message_history(seeded + recent)


def summariser(prepared: PreparedRun) -> Summarise:
    """A summary written by the agent's own chat model, budgeted and billed to the call's run.

    Inside the run's guard and meter, as every ambient call is
    (`can_afford_ambient_call`, `record_ambient_usage`): a summary the budget
    cannot afford is not made, and the seed is the recent turns alone. Booked
    through `record_ambient_usage`, which prices on the chat provider - right
    here, because the chat model is what ran.
    """

    async def summarise(transcript: str) -> str:
        with guarded_by(prepared.built.budget), metered_by(prepared.built.ledger):
            if not await can_afford_ambient_call():
                return ""
            agent = PydanticAgent(prepared.built.agent.model, instructions=_SUMMARY_PROMPT)
            agent.instrument = inherited_instrumentation(prepared.built.agent)
            result = await agent.run(transcript)
            record_ambient_usage(
                result.response.model_name or "summary",
                result.usage,
                prepared.built.budget.provider,
            )
        return result.output

    return summarise
