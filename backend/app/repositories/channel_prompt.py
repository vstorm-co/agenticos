"""Channel prompts: the approvals and questions a chat was offered as buttons."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel_prompt import ChannelPrompt


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


async def answer(
    db: AsyncSession, *, prompt: ChannelPrompt, value: dict[str, Any]
) -> ChannelPrompt:
    prompt.answer = value
    prompt.answered_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(prompt)
    return prompt


async def for_call(db: AsyncSession, *, run_id: UUID, tool_call_id: str) -> list[ChannelPrompt]:
    """Every question one `ask_user_question` call was offered as, in order."""
    result = await db.execute(
        select(ChannelPrompt)
        .where(ChannelPrompt.run_id == run_id, ChannelPrompt.tool_call_id == tool_call_id)
        .order_by(ChannelPrompt.question_index)
    )
    return list(result.scalars().all())
