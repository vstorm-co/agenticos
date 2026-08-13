"""What a run actually did, written down.

Every surface reaches the runner, so every run has always had a row - its cost,
its status, its tokens, and the budget enforced against it. Writing the
*transcript* was the caller's job, and the callers were not equal: web chat
recorded everything, a channel bot recorded two lines of text, and the embedded
widget, a channel mention, the HTTP API and every resumed run recorded nothing at
all. An organization was billed for an answer given to a visitor on a client's
site with no row saying what was asked or what was said back.

So this is not a helper each surface may call. It is called from
:meth:`AgentRunnerService._run`, which is the one place a non-streaming run
executes, for the reason `PreparedRun.stash` gives about the run's budget caps:
a thing every surface has to remember is a thing the next surface will not, and
this one failed by silently recording nothing rather than by raising.

Writes go through the repository rather than `ConversationService.add_message`,
and both departures are deliberate. The conversation comes off the run row,
which is already tenant-checked, so re-resolving it would re-ask a question
already answered. And `add_message` refuses an archived conversation - the right
answer for a person appending a turn, the wrong one here: archiving a thread
must not make the run inside it unaccountable.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic_ai.messages import (
    ModelMessage,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
)

from app.repositories import chat_file as chat_file_repo
from app.repositories import conversation as conversation_repo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.models.agent_run import AgentRun
    from app.db.models.chat_file import ChatFile

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecordedToolCall:
    """One tool call a run made, and what came back from it.

    Attributes:
        tool_call_id: The provider's own id for the call, so a row here and a
            `tool_call` frame on a streaming surface are the same call.
        tool_name: What was called.
        args: What it was called with. Stored because "the agent sent an email"
            is not reviewable and "the agent sent an email to X" is.
        result: What it returned, or - when it failed - the notice that the
            model was asked to retry, never the retry text itself
            (:func:`_result_text`). `None` for a call that never returned - the
            run was parked on it, stopped, or broke before it completed.
    """

    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    result: str | None = None


def tool_retry_notice(part: RetryPromptPart) -> str:
    """What a tool that asked the model to try again may tell a reader.

    A retry's content is written by whichever tool raised: `web_search` turns a
    search provider's failure into a `ModelRetry` built out of the `httpx` or
    SDK exception it caught, so a broken key put "401 Unauthorized for url
    'https://api.tavily.com/search'" - an endpoint, a host, and whatever the
    query string held - in front of everyone watching the run (#681), and on
    the tool-call row every member who can read the run opens weeks later
    (#695). An MCP tool's retry is a third party's string entirely, which is
    why this is one sentence at the two choke points rather than a rule at each
    raise: `run_stream` sends it in the `tool_result` frame, and
    :func:`_result_text` below stores it.

    The model still reads the retry whole: Pydantic AI puts the part into the
    next request itself and nothing here touches that, so the detail that
    decides whether it retries, switches tack or gives up is unchanged. Only
    what is shown and stored is trimmed, and the tool's own text stays in the
    `logger.warning` beside the send or the write.

    The tool's *name* still goes out, because it is what makes the frame worth
    sending: a card that resolves saying which step failed is the difference
    from one that spins for ever. `tool_name` is optional on the part - output
    validation raises a retry that names no tool - hence the two forms.
    """
    called = f"The {part.tool_name} call" if part.tool_name else "A tool call"
    return (
        f"{called} failed and the model was asked to try again. The server log has the full error."
    )


def _result_text(part: ToolReturnPart | RetryPromptPart) -> str:
    """What the row stores as the call's outcome.

    A return is the tool's own answer and is stored whole. A retry's content is
    written by whatever raised - `web_search` builds one out of the vendor
    exception it caught, failing endpoint and query string included, and an MCP
    tool's is a third party's string entirely - so the row holds the same
    sentence the `tool_result` frame sends (#681) and the text itself goes to
    the log beside the write, where run history read weeks later cannot reach
    it (#695). The model is untouched either way: Pydantic AI carries the part
    into the next request itself, and this function only decides what is stored.
    """
    if isinstance(part, RetryPromptPart):
        logger.warning("Tool call %s asked the model to retry: %s", part.tool_call_id, part.content)
        return tool_retry_notice(part)
    return str(part.content)


def tool_calls_in(messages: Sequence[ModelMessage]) -> list[RecordedToolCall]:
    """Every tool call in these messages, each paired with what it returned.

    Pass `result.new_messages()`, never `all_messages()`. A resumed run is handed
    everything up to the park as history, so the wider list would write the first
    attempt's calls a second time under the same run - and a transcript that
    shows one `send_email` twice is one nobody can use to decide whether the
    agent behaved.

    A `RetryPromptPart` counts as a result. A call the model was told to retry
    did happen and did fail, and dropping it would leave the transcript showing
    an argument list with no outcome - which reads as "still running" for ever.

    A result whose call is not here is skipped rather than collected and then
    dropped: it is :func:`settled_calls_in`'s to store, and reading it in both
    places logged a settled retry's vendor text twice. Gating on `calls` is
    sound because a result part sits in the `ModelRequest` that answers its
    call's `ModelResponse`, so the call - when it is in these messages at all -
    has always been seen first.
    """
    calls: dict[str, RecordedToolCall] = {}
    results: dict[str, str] = {}
    for message in messages:
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                calls[part.tool_call_id] = RecordedToolCall(
                    tool_call_id=part.tool_call_id,
                    tool_name=part.tool_name,
                    args=part.args_as_dict(raise_if_invalid=False),
                )
            elif isinstance(part, ToolReturnPart | RetryPromptPart) and part.tool_call_id in calls:
                results[part.tool_call_id] = _result_text(part)
    return [
        RecordedToolCall(
            tool_call_id=call.tool_call_id,
            tool_name=call.tool_name,
            args=call.args,
            result=results.get(call.tool_call_id),
        )
        for call in calls.values()
    ]


def settled_calls_in(messages: Sequence[ModelMessage]) -> dict[str, str]:
    """Returns that arrived without the call they belong to, by tool call id.

    The other half of :func:`tool_calls_in`, and the shape a resume produces. A
    parked call is replayed against a history that already holds its
    `ToolCallPart`, so what is *new* is only its `ToolReturnPart` - which
    `tool_calls_in` drops, having nothing to hang it on. That is why the one call
    a person deliberately reviewed was the one whose output the transcript did not
    hold: the row was written open when the run parked and nothing ever closed it.

    An orphan return outside a resume would mean a provider answered a call nobody
    made, so this is empty for an ordinary run.
    """
    called = {
        part.tool_call_id
        for message in messages
        for part in message.parts
        if isinstance(part, ToolCallPart)
    }
    return {
        part.tool_call_id: _result_text(part)
        for message in messages
        for part in message.parts
        if isinstance(part, ToolReturnPart | RetryPromptPart) and part.tool_call_id not in called
    }


def _what_arrived(attachments: Sequence[ChatFile]) -> str:
    """The user turn's body when files arrived with no words around them.

    A blank user message reads as somebody sending nothing, so a caption-less
    upload names its files instead - the vocabulary `AttachmentRouter` already
    uses for the model's briefing (#704). Only the names: the linked rows carry
    the size and the type.
    """
    return "\n".join(
        f"Attached {'image' if attachment.file_type == 'image' else 'file'}: {attachment.filename}"
        for attachment in attachments
    )


class TranscriptService:
    """Writes a run's turns into the conversation the run belongs to."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def record(
        self,
        run: AgentRun,
        *,
        prompt: str | None,
        answer: str,
        attachments: Sequence[ChatFile] = (),
        tool_calls: Sequence[RecordedToolCall] = (),
        settled: Mapping[str, str] | None = None,
        parked: Collection[str] = (),
        model_label: str | None = None,
    ) -> None:
        """Write whatever this run produced, and never fail the run for it.

        `prompt` is `None` where there is nothing new to record: a resumed run
        picks up at the tool call it stopped on, and inventing a user turn there
        would put words in somebody's mouth.

        `attachments` are the files that arrived with the turn, linked to the row
        holding it - which is how a file becomes something the product can show.
        Without them the only trace of a file posted in a channel was the briefing
        `AttachmentRouter` appends to the prompt for the *model*, so what a person
        read in `/chat` was `co tu widzisz` followed by `--- Attached file: …
        (/uploads/…, 43 KB, image)`. The dashboard's own uploads have been rows
        since they existed; a channel's became nothing at all.

        An empty *prompt* with a file beside it is a turn, because a picture
        posted with no caption is one: the row is what the file hangs off, and
        without it the attachment belongs to nothing. Its body names what
        arrived rather than staying blank - an empty user message reads as
        somebody sending nothing (#704). `None` is different from `""` here:
        a resume passes `None` and no attachments, so it writes no user turn,
        while an empty caption always arrives with the file that makes it one.

        An empty `answer` is written when the run called something, and skipped
        when it did not. A blank assistant message with nothing under it reads as
        the agent replying with silence, but a run that parked, broke or was
        stopped mid-work *did* things - and gating the write on the answer meant
        none of them were recorded. A continuation that ran a command and then
        parked on a second one wrote nothing at all: the command ran, it cost
        money, it changed a workspace, and history showed the run going straight
        from one approval to the next. The tool calls are the record of what
        happened; the answer is only how it ended.

        `settled` closes rows this run wrote *earlier*, which is the only way an
        approved call's output is ever recorded: the row was created open when the
        run parked, and the resume that finally ran it produces the return without
        the call it belongs to (:func:`settled_calls_in`). So the one call somebody
        deliberately reviewed used to be the one call the transcript showed
        finishing with nothing under it.

        `parked` names the calls this run just stopped on, and their rows are
        written `awaiting_approval` rather than `running`. The parked state
        otherwise lives only on `agent_runs` and the `approvals` rows, so a
        reloaded conversation read the one call somebody has to decide about as
        a step that ran (#601). The row is not left that way for ever: a resume
        settles it with what the call returned, and an expiry settles it with
        the timeout notice (:meth:`ApprovalService._settle_expired_run`).

        Never raises, and never poisons the session it shares with the caller.
        The answer has already been produced and the money already spent; losing
        either to a failed write would be the worst possible trade, and the run
        row remains the record that it happened.

        The write runs inside a SAVEPOINT (`begin_nested`) for the second half of
        that promise. A flush that fails here - a constraint, a lost connection -
        leaves the session in a rolled-back state, and `finish()` commits the run
        row two calls later on this same session: without the savepoint, catching
        the exception is not enough, because that commit then fails too and the
        run - its cost, its status - is lost along with the transcript. The
        savepoint rolls back only this write, and the outer transaction the run
        row rides on stays usable.
        """
        if run.conversation_id is None:
            return
        try:
            async with self.db.begin_nested():
                if prompt or attachments:
                    asked = await conversation_repo.create_message(
                        self.db,
                        conversation_id=run.conversation_id,
                        role="user",
                        content=prompt or _what_arrived(attachments),
                        run_id=run.id,
                        # Off the run rather than passed in: the run row already
                        # records which chat account asked, and a second route to
                        # the same fact is a second route to getting it wrong.
                        channel_identity_id=run.channel_identity_id,
                    )
                    await self._attach(asked.id, attachments)
                for tool_call_id, result in (settled or {}).items():
                    await self._settle(run, tool_call_id=tool_call_id, result=result)
                if answer or tool_calls:
                    await self._answer(
                        run.conversation_id,
                        run,
                        answer=answer,
                        tool_calls=tool_calls,
                        parked=parked,
                        model_label=model_label,
                    )
        except Exception:
            # `exception`, not `warning`: this is the only place in this file that
            # swallows one, and a swallowed exception whose cause is recorded
            # nowhere leaves a reader knowing a transcript is missing and nothing
            # about why. The run row survives by design, so the traceback is the
            # only account of what took the transcript with it.
            logger.exception(
                "transcript_write_failed",
                extra={"run_id": str(run.id), "conversation_id": str(run.conversation_id)},
            )

    async def _attach(self, message_id: UUID, attachments: Sequence[ChatFile]) -> None:
        """Link the turn's files to its user message, at no risk to the rest.

        In a SAVEPOINT of its own inside the transcript's, because this is the
        only write here that touches rows the conversation does not own: a
        failure rolls back the link alone, where sharing the outer savepoint
        would cost a run that has already spent money its answer and its tool
        calls over a file. Web chat makes the same trade for the same write, in
        `persist_user_turn`.

        Nothing when nothing was attached - a SAVEPOINT and its release on every
        turn in the deployment is a real cost for a list that is usually empty.

        The link is scoped to each row's own uploader, because the repository
        refuses to move anybody else's file (#706). The rows here were stored by
        `ChannelAttachmentService.receive` for the turn's sender, so grouping by
        owner is one UPDATE in practice - it only splits if a caller ever hands
        it rows from more than one uploader.
        """
        if not attachments:
            return
        by_owner: dict[UUID, list[UUID]] = {}
        for attachment in attachments:
            by_owner.setdefault(attachment.user_id, []).append(attachment.id)
        try:
            async with self.db.begin_nested():
                for owner_id, ids in by_owner.items():
                    await chat_file_repo.link_to_message(
                        self.db,
                        message_id=message_id,
                        file_ids=ids,
                        user_id=owner_id,
                    )
        except Exception:
            logger.exception("transcript_file_link_failed", extra={"message_id": str(message_id)})

    async def _settle(self, run: AgentRun, *, tool_call_id: str, result: str) -> None:
        """Close a call this run left open, if the row is still open.

        Silent when there is no such row. A return with no call in the transcript
        is a call that was never written - a surface that recorded nothing, or a
        run whose park predates the write - and inventing a row here would put a
        step in a turn that has no other trace of it.
        """
        row = await conversation_repo.get_open_tool_call_in_run(
            self.db, run_id=run.id, tool_call_id=tool_call_id
        )
        if row is None:
            return
        await conversation_repo.complete_tool_call(
            self.db, db_tool_call=row, result=result, completed_at=datetime.now(UTC)
        )

    async def _answer(
        self,
        conversation_id: UUID,
        run: AgentRun,
        *,
        answer: str,
        tool_calls: Sequence[RecordedToolCall],
        parked: Collection[str],
        model_label: str | None,
    ) -> None:
        """The assistant turn and the calls it made, attributed to the version.

        `agent_version_id` comes off the run rather than the agent: an agent is
        rewritten between runs, and attributing last Tuesday's answer to the
        spec it has today would rewrite what it was told to do.
        """
        message = await conversation_repo.create_message(
            self.db,
            conversation_id=conversation_id,
            role="assistant",
            content=answer,
            model_name=model_label,
            agent_id=run.agent_id,
            agent_version_id=run.agent_version_id,
            run_id=run.id,
        )
        now = datetime.now(UTC)
        for call in tool_calls:
            row = await conversation_repo.create_tool_call(
                self.db,
                message_id=message.id,
                tool_call_id=call.tool_call_id,
                tool_name=call.tool_name,
                args=call.args,
                started_at=now,
                status="awaiting_approval" if call.tool_call_id in parked else "running",
            )
            if call.result is not None:
                await conversation_repo.complete_tool_call(
                    self.db,
                    db_tool_call=row,
                    result=call.result,
                    completed_at=now,
                )
