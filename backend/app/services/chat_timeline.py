"""What an assistant turn contained, in the order it happened.

A turn is a sequence: the model reasons, writes, calls a tool, writes again. The
message row records the pieces - `content`, `thinking`, `tool_calls` - and until
this existed it recorded no order, so a client replaying a conversation had to
invent one. The only order it could invent was reasoning, then every tool, then
the answer, which is not what a multi-step turn looks like: an introduction
written before the tools ran had nowhere to live in a single `content` column and
was dropped, and the summary written after them reappeared above the work it
described.

So the order is collected here, as the events are streamed, and stored beside the
text. The sequence the client watched is the sequence the client reloads. This is
also why it accumulates the text itself rather than sitting beside a second pair
of lists doing the same thing: two collectors over one stream are two things to
keep in step, and the ordering is only true if there is one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.conversation import MessagePart


@dataclass
class TurnTimeline:
    """The turn's parts as they arrive, and the text they add up to.

    Consecutive deltas of the same kind are one part. A model streams a sentence
    as a dozen `text_delta` frames, and a part per frame would be a dozen bubbles
    where the client showed one - so a part is opened by a change of kind, not by
    a frame.
    """

    parts: list[MessagePart] = field(default_factory=list)

    def add_text(self, delta: str) -> None:
        """Extend the open text part, or open one."""
        self._append("text", delta)

    def add_thinking(self, delta: str) -> None:
        """Extend the open reasoning part, or open one.

        Separate reasoning blocks are joined by a space when they meet, which is
        what the collector this replaced did: providers emit a block per thought
        with no trailing whitespace, and concatenating them ran the last word of
        one into the first of the next.
        """
        open_part = self.parts[-1] if self.parts else None
        if open_part is not None and open_part.type == "thinking" and open_part.text:
            self._append("thinking", f" {delta}")
        else:
            self._append("thinking", delta)

    def add_tool(self, tool_call_id: str) -> None:
        """Record a tool call at this point in the turn.

        The id only. The arguments and the result are a `tool_calls` row, and a
        copy of them here is a copy that disagrees the first time one is re-run.
        """
        self.parts.append(MessagePart(type="tool", tool_call_id=tool_call_id))

    def _append(self, kind: str, delta: str) -> None:
        open_part = self.parts[-1] if self.parts else None
        if open_part is not None and open_part.type == kind:
            open_part.text = (open_part.text or "") + delta
            return
        self.parts.append(MessagePart(type=kind, text=delta))  # ty: ignore[invalid-argument-type]

    @property
    def text(self) -> str:
        """Everything the model wrote, in order, with the tools between removed.

        What the client was shown as `text_delta`, which is what a turn that never
        finished is written down as - there is no result to write instead.
        """
        return "".join(part.text or "" for part in self.parts if part.type == "text")

    @property
    def thinking(self) -> str | None:
        """The reasoning trace, or None when the model produced none.

        None rather than an empty string: the column means "this model does not
        reason" or "it did not this time", and an empty string renders as an
        empty pane somebody can open.
        """
        joined = " ".join(part.text for part in self.parts if part.type == "thinking" and part.text)
        return joined or None

    def stored(self) -> list[MessagePart] | None:
        """The timeline to persist, or None when there is no order worth recording.

        A turn of one part has no sequence to preserve - the row's own columns say
        everything it contained - and writing one would put a JSONB array on every
        plain question-and-answer in the deployment to record that the answer came
        after the question.
        """
        return self.parts if len(self.parts) > 1 else None
