"""An answer Slack itself draws while it is written (#2084).

Slack's AI apps stream a reply rather than have it edited into place:
`chat.startStream` opens it under the question, `chat.appendStream` adds text and
task rows, and `chat.stopStream` ends it. Each tool call is a row in the reply's
timeline that goes from in progress to done or failed - what the other platforms
can only say as a status line the answer then overwrites.

Ending it is where the rest of the native message is put together: the thumbs
that rate the answer, and a table in the answer drawn as a Block Kit table
rather than as pipes and dashes.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from app.services.channels.base import AnswerStep, NativeAnswer, feedback_value

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

FEEDBACK_ACTION = "aos_feedback"
"""The `action_id` the thumbs carry; the press is read from its `value`."""

_MAX_ROWS = 100
_MAX_COLUMNS = 20
"""Slack's limits on a table block; a larger table stays in the text."""

_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _cells(line: str) -> list[str]:
    match = _ROW.match(line)
    return [cell.strip() for cell in match.group(1).split("|")] if match else []


def split_first_table(text: str) -> tuple[str, list[list[str]], str] | None:
    """The text before the first Markdown table, its rows, and the text after.

    A table is a header row, a `---` rule and the rows under it, all of one
    width; anything else is left to the text. `None` when there is no table
    Slack can draw.
    """
    lines = text.split("\n")
    for start in range(len(lines) - 1):
        header = _cells(lines[start])
        if len(header) < 2 or not _RULE.match(lines[start + 1]):
            continue
        rows = [header]
        end = start + 2
        while end < len(lines) and len(_cells(lines[end])) == len(header):
            rows.append(_cells(lines[end]))
            end += 1
        if len(rows) > _MAX_ROWS or len(header) > _MAX_COLUMNS:
            return None
        return "\n".join(lines[:start]).strip(), rows, "\n".join(lines[end:]).strip()
    return None


def feedback_block(run_id: str) -> dict[str, Any]:
    """Thumbs up and down under an answer, each naming the run it rates."""
    return {
        "type": "context_actions",
        "elements": [
            {
                "type": "feedback_buttons",
                "action_id": FEEDBACK_ACTION,
                "positive_button": {
                    "text": {"type": "plain_text", "text": "Helpful"},
                    "accessibility_label": "This answer was helpful",
                    "value": feedback_value(run_id, helpful=True),
                },
                "negative_button": {
                    "text": {"type": "plain_text", "text": "Not helpful"},
                    "accessibility_label": "This answer was not helpful",
                    "value": feedback_value(run_id, helpful=False),
                },
            }
        ],
    }


def answer_blocks(text: str, run_id: str | None) -> list[dict[str, Any]] | None:
    """The finished answer as blocks, or `None` when plain text says it all.

    Blocks only when they add something: a table drawn as one, or the thumbs.
    """
    blocks: list[dict[str, Any]] = []
    table = split_first_table(text)
    if table is not None:
        before, rows, after = table
        if before:
            blocks.append({"type": "markdown", "text": before})
        blocks.append(
            {
                "type": "table",
                "rows": [[{"type": "raw_text", "text": cell} for cell in row] for row in rows],
            }
        )
        if after:
            blocks.append({"type": "markdown", "text": after})
    if run_id is not None:
        blocks.append(feedback_block(run_id))
    return blocks or None


class SlackNativeAnswer(NativeAnswer):
    """One streamed reply, in one thread, for one asker."""

    def __init__(
        self,
        client: AsyncWebClient,
        *,
        channel: str,
        handle: str,
        plan_title: str | None = None,
    ) -> None:
        self._client = client
        self._channel = channel
        self.handle = handle
        self._text = ""
        # Sent with the first step, which is when there starts to be a plan.
        self._plan_title = plan_title

    async def append(self, text: str) -> None:
        await self._client.chat_appendStream(
            channel=self._channel, ts=self.handle, markdown_text=text
        )
        self._text += text

    async def step(self, step: AnswerStep) -> None:
        task: dict[str, Any] = {
            "type": "task_update",
            "id": step.id,
            "title": step.title,
            "status": step.status,
        }
        if step.sources:
            task["sources"] = [
                {"type": "url", "url": source.url, "text": source.title} for source in step.sources
            ]
        chunks: list[dict[str, Any]] = [task]
        if self._plan_title:
            chunks.insert(0, {"type": "plan_update", "title": self._plan_title})
            self._plan_title = None
        await self._client.chat_appendStream(channel=self._channel, ts=self.handle, chunks=chunks)

    async def finish(self, text: str, *, failed: bool, feedback_run_id: str | None) -> None:
        whole = self._text + text
        blocks = answer_blocks(whole, None if failed else feedback_run_id)
        has_table = blocks is not None and any(block["type"] == "table" for block in blocks)
        # A table replaces the text it came from, so the streamed text cannot
        # stay as it is: the message is ended, then rewritten as blocks.
        await self._client.chat_stopStream(
            channel=self._channel,
            ts=self.handle,
            markdown_text=text or None,
            blocks=None if has_table else blocks,
        )
        if has_table:
            await self._client.chat_update(
                channel=self._channel, ts=self.handle, text=whole, blocks=blocks
            )
