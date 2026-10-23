"""Next steps as buttons in a chat (#2301).

An agent with the follow-ups capability ends an answer with up to three steps
from `suggest_next_steps`, which the console draws as buttons. In a chat they
were lost: the tool tells the model not to list them in its answer, and nothing
drew them. Now they are offered under the answer as a message with a button per
step, and a press is the presser saying that step - replayed as their next
message, so it is held to everything a message is: the link, the bot's access
policy, the rate limit, the agent it reaches.

**A press is held to what a request is.** Its value names a stored row and an
index and nothing else, so it cannot be forged into saying words the agent never
offered; and the row is this bot's, claimed and answered once, so a double tap
says the step once.
"""

import json
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_prompt import FOLLOW_UP
from app.repositories import channel_bot_repo, channel_prompt_repo
from app.services.channel_bot import unseal_bot_token
from app.services.channels import get_adapter
from app.services.channels.base import (
    ChannelChoice,
    IncomingMessage,
    IncomingPress,
    PromptMessage,
)
from app.services.transcript import RecordedToolCall

logger = logging.getLogger(__name__)

NEXT_PREFIX = "aosnx:"
"""What a next-step button's value starts with - a message to send, not an answer."""

SUGGEST_NEXT_STEPS = "suggest_next_steps"
"""The follow-ups capability's tool, by the name a run records it under."""

OFFERED = "Next:"
"""The text the buttons sit under; a platform posts no message that is buttons alone."""


def next_value(prompt_id: str, index: int) -> str:
    """The value a next-step button carries: its row, and which step.

    Short for the same reason as `press_value`: a Telegram button holds 64 bytes.
    """
    return f"{NEXT_PREFIX}{prompt_id}:{index}"


def read_next(value: str) -> tuple[str, int] | None:
    """The row and the step a next-step button's value names, or `None`."""
    if not value.startswith(NEXT_PREFIX):
        return None
    prompt_id, _, index = value.removeprefix(NEXT_PREFIX).partition(":")
    return (prompt_id, int(index)) if index.isdigit() else None


def next_steps_of(called: list[RecordedToolCall]) -> list[str]:
    """The steps the turn's last `suggest_next_steps` offered, as the tool kept them.

    A call the tool sent back to the model - too many steps, one too long - has
    the retry notice as its result rather than JSON, and offers nothing.
    """
    for call in reversed(called):
        if call.tool_name != SUGGEST_NEXT_STEPS or call.result is None:
            continue
        try:
            steps = json.loads(call.result).get("steps")
        except ValueError, AttributeError:
            return []
        return [step for step in steps if isinstance(step, str)] if isinstance(steps, list) else []
    return []


class ChannelNextSteps:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def offer(
        self, bot: ChannelBot, incoming: IncomingMessage, *, run_id: UUID, steps: list[str]
    ) -> None:
        """Post the steps under the answer, a button each.

        Never raises: the answer is already posted, and steps that could not be
        offered leave the person typing what they want next, as before.
        """
        try:
            prompt = await channel_prompt_repo.create(
                self.db,
                organization_id=bot.organization_id,
                bot_id=bot.id,
                run_id=run_id,
                platform_chat_id=incoming.platform_chat_id,
                kind=FOLLOW_UP,
                choices=steps,
                chat_type=incoming.chat_type,
            )
            await get_adapter(incoming.platform).send_prompt(
                unseal_bot_token(bot),
                PromptMessage(
                    platform_chat_id=incoming.platform_chat_id,
                    text=OFFERED,
                    choices=[
                        ChannelChoice(label=step, value=next_value(prompt.id.hex, index))
                        for index, step in enumerate(steps)
                    ],
                    bot_id=str(bot.id),
                    api_base_url=bot.api_base_url,
                ),
            )
        except Exception:
            logger.exception("Could not offer run %s's next steps on %s", run_id, incoming.platform)

    async def take(self, press: IncomingPress) -> IncomingMessage | None:
        """The message a press stands for, or `None` when it stands for nothing.

        Nothing for a value that is not a step, a bot that is gone or switched
        off, a row of another bot, or a row already pressed. The pressed message
        then reads the step instead of its buttons.
        """
        parsed = read_next(press.value)
        if parsed is None:
            return None
        prompt_id, index = parsed
        try:
            prompt_uuid = UUID(hex=prompt_id)
        except ValueError:
            return None
        bot = await channel_bot_repo.get_for_inbound(self.db, UUID(press.bot_id))
        if bot is None or not bot.is_active:
            return None
        prompt = await channel_prompt_repo.claim(self.db, prompt_uuid, bot_id=bot.id)
        if prompt is None:
            return None
        adapter = get_adapter(press.platform)
        token = unseal_bot_token(bot)
        await adapter.acknowledge(token, press)
        if (
            prompt.kind != FOLLOW_UP
            or prompt.chat_type is None
            or prompt.answered_at is not None
            or index >= len(prompt.choices)
        ):
            return None
        step = prompt.choices[index]
        await channel_prompt_repo.answer(self.db, prompt=prompt, value={"step": step})
        await adapter.settle_prompt(token, press, f"→ {step}")
        return IncomingMessage(
            platform=press.platform,
            bot_id=press.bot_id,
            platform_user_id=press.platform_user_id,
            platform_chat_id=prompt.platform_chat_id,
            chat_type=prompt.chat_type,
            text=step,
            platform_username=press.platform_username,
            # The buttons' own message: what the answer replies to, and - pressed
            # once - a delivery that cannot be claimed twice.
            message_id=press.message_id,
            # Pressing the bot's own button is speaking to it.
            addressed=True,
        )
