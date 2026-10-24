"""Channel prompts: the approvals and questions a chat was offered as buttons."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.channel_prompt import QUESTION, ChannelPrompt


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    bot_id: UUID,
    run_id: UUID,
    platform_chat_id: str,
    kind: str,
    choices: list[str],
    approval_id: UUID | None = None,
    tool_call_id: str | None = None,
    question_index: int | None = None,
    multi_select: bool = False,
    allow_custom: bool = False,
    chat_type: str | None = None,
) -> ChannelPrompt:
    prompt = ChannelPrompt(
        organization_id=organization_id,
        bot_id=bot_id,
        run_id=run_id,
        platform_chat_id=platform_chat_id,
        kind=kind,
        choices=choices,
        approval_id=approval_id,
        tool_call_id=tool_call_id,
        question_index=question_index,
        multi_select=multi_select,
        allow_custom=allow_custom,
        chat_type=chat_type,
    )
    db.add(prompt)
    await db.flush()
    await db.refresh(prompt)
    return prompt


async def claim(db: AsyncSession, prompt_id: UUID, *, bot_id: UUID) -> ChannelPrompt | None:
    """The prompt a press names, held for the rest of the transaction.

    Scoped to the bot the press arrived on, so a press relayed through another
    bot - in another organization - finds nothing. Locked so a double tap is
    answered once: the second waits here and finds it answered.
    """
    result = await db.execute(
        select(ChannelPrompt)
        .where(ChannelPrompt.id == prompt_id, ChannelPrompt.bot_id == bot_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def claim_typed(
    db: AsyncSession, *, bot_id: UUID, platform_chat_id: str, user_id: UUID
) -> ChannelPrompt | None:
    """The oldest question in this chat that this person may answer by typing.

    Only a question put to them - the run's own person - on a run still waiting
    for it, and held like a press's prompt so two quick messages answer it once.
    """
    result = await db.execute(
        select(ChannelPrompt)
        .join(AgentRun, AgentRun.id == ChannelPrompt.run_id)
        .where(
            ChannelPrompt.bot_id == bot_id,
            ChannelPrompt.platform_chat_id == platform_chat_id,
            ChannelPrompt.kind == QUESTION,
            ChannelPrompt.allow_custom.is_(True),
            ChannelPrompt.answered_at.is_(None),
            AgentRun.user_id == user_id,
            # A publisher standing in for a stranger was never the one asked.
            AgentRun.initiated_by_publisher_fallback.is_(False),
            AgentRun.status == RunStatus.AWAITING_ANSWER.value,
        )
        .order_by(ChannelPrompt.created_at, ChannelPrompt.question_index)
        .limit(1)
        .with_for_update(of=ChannelPrompt)
    )
    return result.scalar_one_or_none()


async def answer(
    db: AsyncSession, *, prompt: ChannelPrompt, value: dict[str, Any]
) -> ChannelPrompt:
    prompt.answer = value
    prompt.answered_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(prompt)
    return prompt


async def pick(db: AsyncSession, *, prompt: ChannelPrompt, selected: list[str]) -> ChannelPrompt:
    """Record a multi-select question's choices so far, leaving it unanswered."""
    prompt.answer = {"selected": selected}
    await db.flush()
    await db.refresh(prompt)
    return prompt


async def delete(db: AsyncSession, prompts: list[ChannelPrompt]) -> None:
    """Remove prompts that never reached the chat."""
    for prompt in prompts:
        await db.delete(prompt)
    await db.flush()


async def for_call(db: AsyncSession, *, run_id: UUID, tool_call_id: str) -> list[ChannelPrompt]:
    """Every question one `ask_user_question` call was offered as, in order."""
    result = await db.execute(
        select(ChannelPrompt)
        .where(ChannelPrompt.run_id == run_id, ChannelPrompt.tool_call_id == tool_call_id)
        .order_by(ChannelPrompt.question_index)
    )
    return list(result.scalars().all())
