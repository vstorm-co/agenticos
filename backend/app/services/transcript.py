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
from collections.abc import Mapping, Sequence
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

from app.repositories import chat_file_repo
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
        result: What it returned, or the retry message when it failed. `None`
            for a call that never returned - the run was parked on it, stopped,
            or broke before it completed.
    """

    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    result: str | None = None


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
            elif isinstance(part, ToolReturnPart | RetryPromptPart):
                results[part.tool_call_id] = str(part.content)
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
        part.tool_call_id: str(part.content)
        for message in messages
        for part in message.parts
        if isinstance(part, ToolReturnPart | RetryPromptPart) and part.tool_call_id not in called
    }


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
        tool_calls: Sequence[RecordedToolCall] = (),
        settled: Mapping[str, str] | None = None,
        model_label: str | None = None,
        attachments: Sequence[ChatFile] = (),
    ) -> None:
        """Write whatever this run produced, and never fail the run for it.

        `prompt` is `None` where there is nothing new to record: a resumed run
        picks up at the tool call it stopped on, and inventing a user turn there
        would put words in somebody's mouth.

        `attachments` are the files that arrived with that prompt, and they are
        linked to the user turn written here because this is where that message
        first exists. A channel bot stored a `ChatFile`, fed it to the agent and
        then left `message_id` NULL for ever: `chat_files` carries no
        organization, so an unlinked row is scoped by `user_id` alone and the
        conversation it belongs to does not know the file exists (#690). Only
        web chat linked them, from the one surface that writes its own
        transcript.

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
                if prompt:
                    user_message = await conversation_repo.create_message(
                        self.db,
                        conversation_id=run.conversation_id,
                        role="user",
                        content=prompt,
                        run_id=run.id,
                    )
                    await self._attach(user_message.id, attachments)
                for tool_call_id, result in (settled or {}).items():
                    await self._settle(run, tool_call_id=tool_call_id, result=result)
                if answer or tool_calls:
                    await self._answer(
                        run.conversation_id,
                        run,
                        answer=answer,
                        tool_calls=tool_calls,
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
        """
        if not attachments:
            return
        try:
            async with self.db.begin_nested():
                await chat_file_repo.link_to_message(
                    self.db,
                    message_id=message_id,
                    file_ids=[attachment.id for attachment in attachments],
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
            )
            if call.result is not None:
                await conversation_repo.complete_tool_call(
                    self.db,
                    db_tool_call=row,
                    result=call.result,
                    completed_at=now,
                )
