"""Approvals and questions in a chat, as buttons (#2064, #2067, #2068).

A run started from a chat can stop for a person: a gated tool call waits for a
decision, or the agent asks an `ask_user` question. Before this, the chat was
told to go to the console. Now the chat is offered the choices where it is - a
message per approval with Approve and Reject, a message per question with its
options - and a press decides or answers, continues the run, and posts what it
said in the same chat.

**A press is a request from somebody, and is held to everything a request is.**
It names a stored prompt and a choice and nothing else, so it cannot be forged
into deciding something it was not offered for; the presser is resolved through
their linked account and acts with their own permissions - `approvals:decide` to
decide, and only the person a question was put to may answer it. An unlinked
presser is told to link, like an unlinked sender.
"""

from __future__ import annotations

import json
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, AuthorizationError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.agent_run import ApprovalStatus
from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_prompt import APPROVAL, QUESTION, ChannelPrompt
from app.repositories import (
    agent_run_repo,
    channel_bot_repo,
    channel_identity_repo,
    channel_prompt_repo,
    member_repo,
)
from app.services.agent_runner import AgentRunnerService, RunSegment
from app.services.approvals import ApprovalService
from app.services.channel_bot import unseal_bot_token
from app.services.channels import get_adapter
from app.services.channels.base import (
    ChannelChoice,
    IncomingPress,
    OutgoingMessage,
    PromptMessage,
    press_value,
    read_press,
)

logger = logging.getLogger(__name__)

APPROVE = "Approve"
REJECT = "Reject"
SKIP = "Skip"
LINK_FIRST = "Link your account first - send /link to this bot - and press again."
ALREADY = "That has already been answered."
NOT_YOURS = "Only somebody who may approve tool calls can decide this one."
NOBODY = UUID(int=0)
_ARGS_SHOWN = 300
"""How much of a gated call's arguments the approval message quotes."""


async def linked_member(
    db: AsyncSession, bot: ChannelBot, platform: str, platform_user_id: str
) -> AuthContext | None:
    """A chat user, as a member acting with their own role, or `None` if unlinked."""
    identity = await channel_identity_repo.get_by_platform_user(db, platform, platform_user_id)
    if identity is None or identity.user_id is None:
        return None
    membership = await member_repo.get_active(
        db, organization_id=bot.organization_id, user_id=identity.user_id
    )
    if membership is None:
        return None
    return AuthContext(
        user_id=identity.user_id,
        organization_id=bot.organization_id,
        role=membership.role,
        channel_identity_id=identity.id,
    )


def _arguments(args: dict[str, object]) -> str:
    shown = json.dumps(args, ensure_ascii=False, default=str)
    return shown if len(shown) <= _ARGS_SHOWN else f"{shown[:_ARGS_SHOWN]}…"


class ChannelPrompts:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.runner = AgentRunnerService(db)

    async def offer(
        self, bot: ChannelBot, *, platform: str, platform_chat_id: str, run_id: UUID
    ) -> None:
        """Put what the run is waiting on in front of the chat, one message each.

        Never raises: the answer the turn produced is already posted, and a
        prompt that could not be sent leaves the run where the console and the
        approvals queue still reach it.
        """
        try:
            await self._offer(
                bot, platform=platform, platform_chat_id=platform_chat_id, run_id=run_id
            )
        except Exception:
            logger.exception("Could not offer run %s's prompts on %s", run_id, platform)

    async def _offer(
        self, bot: ChannelBot, *, platform: str, platform_chat_id: str, run_id: UUID
    ) -> None:
        run = await agent_run_repo.get_run(self.db, run_id, organization_id=bot.organization_id)
        if run is None:
            return
        reader = AuthContext(
            # Whose questions they are: the questions are read back for the person
            # the run asked, and the approvals for the organization. A run nobody
            # is named on has no questions anybody here can answer.
            user_id=run.user_id or NOBODY,
            organization_id=bot.organization_id,
            role=OrgRoleName.VIEWER,
        )
        adapter = get_adapter(platform)
        token = unseal_bot_token(bot)
        for call in await self.runner.parked_calls(reader, run):
            prompt = await channel_prompt_repo.create(
                self.db,
                organization_id=bot.organization_id,
                bot_id=bot.id,
                run_id=run.id,
                platform_chat_id=platform_chat_id,
                kind=APPROVAL,
                approval_id=call.id,
                choices=[APPROVE, REJECT],
            )
            await adapter.send_prompt(
                token,
                self._message(
                    bot,
                    prompt,
                    f"The agent wants to run `{call.tool_name}` with {_arguments(call.tool_args)}. "
                    "Approve it?",
                    skippable=False,
                ),
            )
        for parked in await self.runner.parked_questions(reader, run):
            for index, question in enumerate(parked.questions):
                prompt = await channel_prompt_repo.create(
                    self.db,
                    organization_id=bot.organization_id,
                    bot_id=bot.id,
                    run_id=run.id,
                    platform_chat_id=platform_chat_id,
                    kind=QUESTION,
                    tool_call_id=parked.tool_call_id,
                    question_index=index,
                    choices=[option.label for option in question.options],
                )
                heading = f"*{question.header}* - " if question.header else ""
                await adapter.send_prompt(
                    token,
                    self._message(bot, prompt, f"{heading}{question.question}", skippable=True),
                )

    @staticmethod
    def _message(
        bot: ChannelBot, prompt: ChannelPrompt, text: str, *, skippable: bool
    ) -> PromptMessage:
        styles = {APPROVE: "primary", REJECT: "danger"} if prompt.kind == APPROVAL else {}
        choices = [
            ChannelChoice(
                label=label, value=press_value(prompt.id.hex, index), style=styles.get(label)
            )
            for index, label in enumerate(prompt.choices)
        ]
        if skippable:
            choices.append(ChannelChoice(label=SKIP, value=press_value(prompt.id.hex, None)))
        return PromptMessage(
            platform_chat_id=prompt.platform_chat_id,
            text=text,
            choices=choices,
            bot_id=str(bot.id),
            api_base_url=bot.api_base_url,
        )

    async def press(self, press: IncomingPress) -> None:
        """Decide or answer what a button was offered for, and continue the run."""
        parsed = read_press(press.value)
        if parsed is None:
            return
        prompt_id, choice = parsed
        try:
            prompt_uuid = UUID(hex=prompt_id)
        except ValueError:
            return
        bot = await channel_bot_repo.get_for_inbound(self.db, UUID(press.bot_id))
        if bot is None or not bot.is_active:
            return
        prompt = await channel_prompt_repo.claim(self.db, prompt_uuid, bot_id=bot.id)
        if prompt is None:
            return
        adapter = get_adapter(press.platform)
        token = unseal_bot_token(bot)
        await adapter.acknowledge(token, press)

        async def say(text: str) -> None:
            await adapter.send_message(
                token,
                OutgoingMessage(
                    platform_chat_id=prompt.platform_chat_id,
                    text=text,
                    api_base_url=bot.api_base_url,
                ),
            )

        if prompt.answered_at is not None:
            await say(ALREADY)
            return
        ctx = await linked_member(self.db, bot, press.platform, press.platform_user_id)
        if ctx is None:
            await say(LINK_FIRST)
            return
        try:
            segment = await (
                self._decide(ctx, prompt, choice)
                if prompt.kind == APPROVAL
                else self._answer(ctx, prompt, choice)
            )
        except AppException as exc:
            await say(exc.message)
            return
        if segment is not None:
            await adapter.settle_prompt(token, press, self._chosen(prompt))
            await say(segment.output or "Done.")
            await self.offer(
                bot,
                platform=press.platform,
                platform_chat_id=prompt.platform_chat_id,
                run_id=prompt.run_id,
            )
        else:
            await adapter.settle_prompt(token, press, self._chosen(prompt))

    async def _decide(
        self, ctx: AuthContext, prompt: ChannelPrompt, choice: int | None
    ) -> RunSegment | None:
        """Record the decision; continue the run once nothing else is pending."""
        if not ctx.has(Perm.APPROVALS_DECIDE):
            raise AuthorizationError(message=NOT_YOURS)
        if prompt.approval_id is None:  # pragma: no cover - the table's check constraint
            return None
        approved = choice == 0
        await ApprovalService(self.db).decide(ctx, prompt.approval_id, approved=approved)
        await channel_prompt_repo.answer(self.db, prompt=prompt, value={"approved": approved})
        approvals = await agent_run_repo.list_approvals_for_run(
            self.db, run_id=prompt.run_id, organization_id=ctx.organization_id
        )
        if any(approval.status == ApprovalStatus.PENDING.value for approval in approvals):
            return None
        return await self.runner.resume(ctx, prompt.run_id)

    async def _answer(
        self, ctx: AuthContext, prompt: ChannelPrompt, choice: int | None
    ) -> RunSegment | None:
        """Record the pick; answer the call once every one of its questions is."""
        picked = (
            {"selected": [prompt.choices[choice]]}
            if choice is not None and choice < len(prompt.choices)
            else {"skipped": True}
        )
        if prompt.tool_call_id is None:  # pragma: no cover - the table's check constraint
            return None
        await channel_prompt_repo.answer(self.db, prompt=prompt, value=picked)
        asked = await channel_prompt_repo.for_call(
            self.db, run_id=prompt.run_id, tool_call_id=prompt.tool_call_id
        )
        if any(row.answer is None for row in asked):
            return None
        return await self.runner.answer(
            ctx, prompt.run_id, {prompt.tool_call_id: [row.answer or {} for row in asked]}
        )

    @staticmethod
    def _chosen(prompt: ChannelPrompt) -> str:
        """What the pressed message reads once its buttons are gone."""
        answer = prompt.answer or {}
        if prompt.kind == APPROVAL:
            return "Approved." if answer.get("approved") else "Rejected."
        selected = answer.get("selected")
        return f"Answered: {selected[0]}" if isinstance(selected, list) and selected else "Skipped."
