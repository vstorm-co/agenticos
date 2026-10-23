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

import logging
import re
from functools import cache
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import all_capabilities
from app.core.exceptions import AppException, AuthorizationError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.agent_run import AgentRun, ApprovalStatus
from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_prompt import APPROVAL, QUESTION, ChannelPrompt
from app.repositories import (
    agent_run_repo,
    channel_bot_repo,
    channel_identity_repo,
    channel_prompt_repo,
    member_repo,
)
from app.services.agent_runner import AgentRunnerService, PausedRunState, RunSegment
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
DONE = "Done"
LINK_FIRST = "Link your account first - send /link to this bot - and press again."
ALREADY = "That has already been answered."
NOT_YOURS = "Only somebody who may approve tool calls can decide this one."
NOT_ASKED = "This question was asked of somebody else."
TYPE_IT = "Or reply here with your own answer."
NOBODY = UUID(int=0)
_SUMMARY_SHOWN = 200
"""How much of a gated call's telling argument the approval message quotes."""

_TELLING = (
    "command",
    "cmd",
    "query",
    "q",
    "url",
    "path",
    "file_path",
    "title",
    "subject",
    "name",
    "to",
    "text",
    "content",
    "message",
    "prompt",
    "task",
)
"""The arguments that say what a call is about, most telling first - the console's list."""


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


@cache
def _builtin_tools() -> frozenset[str]:
    """Every tool a capability of this deployment declares, by its stable id."""
    return frozenset(tool.id for definition in all_capabilities() for tool in definition.tools)


def call_action(tool_name: str) -> str:
    """What a gated call does, in words: "write memory", "search in Notion".

    A tool none of our capabilities declares came from an MCP server, which
    prefixes its tools with the service's key - and often repeats itself:
    Notion's search is `notion_notion-search`. The service is named once.
    """
    if tool_name not in _builtin_tools():
        service, _, action = tool_name.partition("_")
        words = [w for w in re.split(r"[-_]+", action) if w and w.lower() != service.lower()]
        if service and words:
            return f"{' '.join(words)} in {service.capitalize()}"
    return tool_name.replace("_", " ")


def call_summary(args: dict[str, object]) -> str | None:
    """The one argument that says what the call is about - its first line, cut short."""
    strings = [
        (key, value) for key, value in args.items() if isinstance(value, str) and value.strip()
    ]
    if not strings:
        return None
    by_key = dict(strings)
    telling = next((by_key[key] for key in _TELLING if key in by_key), strings[0][1])
    line = telling.strip().splitlines()[0].strip()
    return line if len(line) <= _SUMMARY_SHOWN else f"{line[: _SUMMARY_SHOWN - 1]}…"


def approval_text(tool_name: str, args: dict[str, object], account: str | None = None) -> str:
    """The approval message: what the agent wants to do and what about, as the agent says it.

    The agent is the one speaking in the chat, so it asks in its own voice. The
    rest of the arguments stay in the console; a chat message with an MCP
    schema's twenty fields in it was read by nobody. Which account it acts as is
    said where the call names one - two mailboxes make "send mail" a question.
    """
    summary = call_summary(args)
    about = f": “{summary}”" if summary else "."
    acting = f" as *{account}*" if account else ""
    return f"I need your approval to *{call_action(tool_name)}*{acting}{about}"


def _parked_calls(run: AgentRun) -> list[str]:
    """The `ask_user` calls a run is parked on, in the order it asked them."""
    return PausedRunState.model_validate(run.paused_state).questions


def _selected(prompt: ChannelPrompt) -> list[str]:
    """The choices a multi-select question has collected so far."""
    selected = (prompt.answer or {}).get("selected")
    return [str(label) for label in selected] if isinstance(selected, list) else []


def _picked_so_far(picked: list[str]) -> str:
    if not picked:
        return f"Nothing picked yet. Choose one or more, then press {DONE}."
    return f"Picked: {', '.join(picked)}. Press {DONE} when that is all."


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
                    approval_text(call.tool_name, call.tool_args, call.account),
                    skippable=False,
                ),
            )
        for parked in await self.runner.parked_questions(reader, run):
            offered: list[ChannelPrompt] = []
            try:
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
                        multi_select=question.multi_select,
                        # A question with no options can only be answered in words.
                        allow_custom=question.allow_custom or not question.options,
                    )
                    offered.append(prompt)
                    heading = f"*{question.header}* - " if question.header else ""
                    typed = f"\n{TYPE_IT}" if prompt.allow_custom else ""
                    await adapter.send_prompt(
                        token,
                        self._message(
                            bot, prompt, f"{heading}{question.question}{typed}", skippable=True
                        ),
                    )
            except Exception:
                # A call is answered once all its rows are, so a row the chat never
                # saw would hold it forever. None of them stay: the console still
                # reaches the question.
                await channel_prompt_repo.delete(self.db, offered)
                raise

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
        if prompt.multi_select:
            done = press_value(prompt.id.hex, len(prompt.choices))
            choices.append(ChannelChoice(label=DONE, value=done, style="primary"))
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
            if prompt.multi_select and choice is not None and choice < len(prompt.choices):
                picked = await self._toggle(ctx, prompt, choice)
                await say(_picked_so_far(picked))
                return
            segment = await self._settle(ctx, prompt, choice)
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

    async def reply(
        self,
        bot: ChannelBot,
        *,
        platform: str,
        platform_chat_id: str,
        platform_user_id: str,
        text: str,
    ) -> bool:
        """Answer, with a message, the question this chat put to its sender.

        A question that takes an answer in the person's own words is offered with
        its buttons and a line saying they may type instead; this is the typing.
        The oldest such question for them in the chat takes the message whole.
        `False` when there is none, and the message is a turn like any other.
        """
        ctx = await linked_member(self.db, bot, platform, platform_user_id)
        if ctx is None or ctx.user_id is None or not text.strip():
            return False
        prompt = await channel_prompt_repo.claim_typed(
            self.db, bot_id=bot.id, platform_chat_id=platform_chat_id, user_id=ctx.user_id
        )
        if prompt is None:
            return False
        adapter = get_adapter(platform)
        token = unseal_bot_token(bot)

        async def say(said: str) -> None:
            await adapter.send_message(
                token,
                OutgoingMessage(
                    platform_chat_id=platform_chat_id,
                    text=said,
                    api_base_url=bot.api_base_url,
                ),
            )

        try:
            segment = await self._settle(ctx, prompt, None, typed=text.strip())
        except AppException as exc:
            await say(exc.message)
            return True
        if segment is None:
            # The call has more questions still open; this one is taken.
            await say(self._chosen(prompt))
            return True
        await say(segment.output or "Done.")
        await self.offer(
            bot, platform=platform, platform_chat_id=platform_chat_id, run_id=prompt.run_id
        )
        return True

    async def _settle(
        self,
        ctx: AuthContext,
        prompt: ChannelPrompt,
        choice: int | None,
        *,
        typed: str | None = None,
    ) -> RunSegment | None:
        """Record the press and continue the run - or neither, when the run refuses.

        The decision (or answer) and the prompt's answered mark are written before
        the run is resumed. A resume refused before it starts - a model profile or
        a key gone missing meanwhile - would otherwise commit them anyway, leave
        the run parked and every later press answered `ALREADY`, with no way to
        try again. A savepoint takes them back. Once the resume has committed its
        own work the savepoint is gone with it, and what it wrote stands.
        """
        # The run's row, held for the rest of the transaction: two presses on two
        # questions (or two approvals) of one run each lock only their own prompt,
        # and both could read the other as unanswered and neither continue the
        # run. Held, the second waits and then sees the first's answer.
        await agent_run_repo.claim_parked_run(
            self.db, prompt.run_id, organization_id=ctx.organization_id
        )
        savepoint = await self.db.begin_nested()
        try:
            segment = await (
                self._decide(ctx, prompt, choice)
                if prompt.kind == APPROVAL
                else self._answer(ctx, prompt, choice, typed)
            )
        except AppException:
            if savepoint.is_active:
                await savepoint.rollback()
            raise
        if savepoint.is_active:
            await savepoint.commit()
        return segment

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
        self, ctx: AuthContext, prompt: ChannelPrompt, choice: int | None, typed: str | None
    ) -> RunSegment | None:
        """Record the pick, or the typed answer; answer the call once every one of its questions is.

        Raises:
            AuthorizationError: The presser is not the person the run asked -
                refused before anything is written, so a colleague's press in a
                shared channel leaves the question for its person.
        """
        await self._require_asked(ctx, prompt)
        if prompt.tool_call_id is None:  # pragma: no cover - the table's check constraint
            return None
        so_far = _selected(prompt)
        if typed is not None:
            picked: dict[str, object] = {"answer": typed}
        elif prompt.multi_select and choice == len(prompt.choices):
            picked = {"selected": so_far} if so_far else {"skipped": True}
        elif choice is not None and choice < len(prompt.choices):
            picked = {"selected": [prompt.choices[choice]]}
        else:
            picked = {"skipped": True}
        await channel_prompt_repo.answer(self.db, prompt=prompt, value=picked)
        # Every call the run is parked on, not only this one's: a turn can ask
        # through several `ask_user` calls, and one left out is answered as
        # declined - the run went on before the person reached the others.
        run = await agent_run_repo.get_run(
            self.db, prompt.run_id, organization_id=ctx.organization_id
        )
        parked = [] if run is None or run.paused_state is None else _parked_calls(run)
        responses: dict[str, list[object]] = {}
        for tool_call_id in parked:
            asked = await channel_prompt_repo.for_call(
                self.db, run_id=prompt.run_id, tool_call_id=tool_call_id
            )
            if any(row.answer is None for row in asked):
                return None
            if asked:
                responses[tool_call_id] = [row.answer or {} for row in asked]
        return await self.runner.answer(ctx, prompt.run_id, responses)

    async def _require_asked(self, ctx: AuthContext, prompt: ChannelPrompt) -> None:
        """Refuse anybody but the person the run asked, before anything is written."""
        run = await agent_run_repo.get_run(
            self.db, prompt.run_id, organization_id=ctx.organization_id
        )
        if run is None or run.user_id != ctx.user_id:
            raise AuthorizationError(message=NOT_ASKED)

    async def _toggle(self, ctx: AuthContext, prompt: ChannelPrompt, choice: int) -> list[str]:
        """Add or remove one choice of a multi-select question; it stays open."""
        await self._require_asked(ctx, prompt)
        label = prompt.choices[choice]
        so_far = _selected(prompt)
        picked = [c for c in so_far if c != label] if label in so_far else [*so_far, label]
        await channel_prompt_repo.pick(self.db, prompt=prompt, selected=picked)
        return picked

    @staticmethod
    def _chosen(prompt: ChannelPrompt) -> str:
        """What the pressed message reads once its buttons are gone."""
        answer = prompt.answer or {}
        if prompt.kind == APPROVAL:
            return "Approved." if answer.get("approved") else "Rejected."
        typed = answer.get("answer")
        if isinstance(typed, str) and typed:
            return f"Answered: {typed}"
        selected = answer.get("selected")
        if not isinstance(selected, list) or not selected:
            return "Skipped."
        return f"Answered: {', '.join(str(label) for label in selected)}"
