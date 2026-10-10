"""Thumbs under a channel answer, recorded as message ratings (#2084).

The console has always let somebody rate an answer; a chat had no way to. A
finished channel answer now carries a thumbs-up and a thumbs-down whose value
names the run that answered, and a press rates that run's answer as the presser
- the same rating row the console writes, so it shows up wherever ratings do.

**A press is held to what a request is.** The value names a run and a verdict and
nothing else; the run must be this bot's organization's, and the presser must be
a linked member, because a rating is somebody's and an unlinked chat user is
nobody here. An unlinked press is dropped rather than answered: being told to
link an account in order to say "this was helpful" is a worse experience than the
thumbs simply not counting.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel_bot import ChannelBot
from app.repositories import agent_run_repo, channel_bot_repo, conversation_repo
from app.repositories import message_rating_repo as rating_repo
from app.services.channel_bot import unseal_bot_token
from app.services.channels import get_adapter
from app.services.channels.base import FeedbackComment, IncomingPress, read_feedback
from app.services.channels.prompts import linked_member

logger = logging.getLogger(__name__)


class ChannelFeedback:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def rate(self, press: IncomingPress) -> bool:
        """Record what a thumbs button says about the answer it was under.

        A thumbs-down then asks what was wrong, where the platform has a form to
        ask it in. Returns whether a rating was written; `False` for anything that
        names no run of this bot's organization, or a presser who is not a linked
        member.
        """
        parsed = read_feedback(press.value)
        if parsed is None:
            return False
        run_hex, helpful = parsed
        bot = await channel_bot_repo.get_for_inbound(self.db, UUID(press.bot_id))
        if bot is None or not bot.is_active:
            return False
        adapter = get_adapter(press.platform)
        token = unseal_bot_token(bot)
        # Telegram spins the pressed button until it is told; whatever follows.
        await adapter.acknowledge(token, press)
        if not await self._record(
            bot, press.platform, press.platform_user_id, run_hex, rating=1 if helpful else -1
        ):
            return False
        await adapter.settle_feedback(token, press, helpful)
        if not helpful:
            try:
                await adapter.ask_feedback_comment(token, press, run_hex, bot_id=press.bot_id)
            except Exception:
                logger.warning("Could not ask what was wrong with an answer", exc_info=True)
        return True

    async def comment(self, comment: FeedbackComment) -> bool:
        """Keep what somebody said was wrong, on their rating of that answer."""
        bot = await channel_bot_repo.get_for_inbound(self.db, UUID(comment.bot_id))
        if bot is None or not bot.is_active:
            return False
        return await self._record(
            bot, comment.platform, comment.platform_user_id, comment.run_id, comment=comment.text
        )

    async def _record(
        self,
        bot: ChannelBot,
        platform: str,
        platform_user_id: str,
        run_hex: str,
        *,
        rating: int | None = None,
        comment: str | None = None,
    ) -> bool:
        """Write a rating, a comment on one, or both, as the linked member.

        A comment with no rating yet is a thumbs-down: it only arrives from the
        form a thumbs-down opened.
        """
        try:
            run_id = UUID(run_hex)
        except ValueError:
            return False
        run = await agent_run_repo.get_run(self.db, run_id, organization_id=bot.organization_id)
        if run is None:
            return False
        ctx = await linked_member(self.db, bot, platform, platform_user_id)
        if ctx is None or ctx.user_id is None:
            logger.info("Feedback from an unlinked %s user ignored", platform)
            return False
        answers = [
            message
            for message in await conversation_repo.get_messages_by_run(self.db, run.id)
            if message.role == "assistant"
        ]
        if not answers:
            return False
        answer = answers[-1]
        existing = await rating_repo.get_rating_by_message_and_user(self.db, answer.id, ctx.user_id)
        if existing is None:
            await rating_repo.create_rating(
                self.db,
                message_id=answer.id,
                user_id=ctx.user_id,
                rating=-1 if rating is None else rating,
                comment=comment,
            )
        else:
            await rating_repo.update_rating(
                self.db,
                existing,
                new_rating=existing.rating if rating is None else rating,
                comment=existing.comment if comment is None else comment,
            )
        return True
