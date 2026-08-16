"""Rebuilding a stored conversation into what a model reads.

Its own module rather than a section of `agent.py`, because a conversation is
replayed by everything that answers one - the chat socket, a channel, the widget
and the service that builds a thread's history - and `agent.py` reaches for
`app.api.deps`, which reaches back for `ConversationService`.
"""

from __future__ import annotations

from typing import NotRequired, TypedDict

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.usage import RequestUsage


class HistoryMessage(TypedDict):
    """One stored turn, as the replayer wants it.

    `context_used_tokens` is `NotRequired` because a surface may not have it - a
    turn from before the column existed, or a run that reached no model - and
    because a caller that only has text is still a legitimate caller.
    """

    role: str
    content: str
    context_used_tokens: NotRequired[int | None]


def build_message_history(history: list[HistoryMessage]) -> list[ModelRequest | ModelResponse]:
    """Convert conversation history to PydanticAI message format.

    **An answer is replayed with the size of the request it came out of**, and the
    reason is not accounting. The compaction estimator anchors on the most recent
    response carrying provider usage: that response's `input_tokens` measured the
    whole request - the instructions, every tool schema, every prior message - so
    anchored, the estimate is the provider's own number rather than a count of
    characters. Replayed as bare text it has nothing to anchor on and falls back
    to ~4 characters per token, which on a real agent here saw 9 tokens where the
    provider had charged for 3,859. A trigger measuring that never fires, and the
    context gauge beside it - which reads the provider's number - sat at 77% while
    nothing happened.

    Absent where it was never recorded: a turn from before the columns existed, or
    one whose cost could not be read. The estimate is then what it always was.
    """
    model_history: list[ModelRequest | ModelResponse] = []

    for msg in history:
        content = msg["content"]
        # An empty text part is not history, it is a 400: Anthropic rejects one,
        # and a row with no text carries nothing to the model regardless. A
        # caption-less file is recorded as an empty user turn so the file has a
        # row to hang off (transcript.py), but the file's bytes are not in the
        # history this reconstructs - so the empty row is pure liability here.
        if not content.strip():
            continue
        if msg["role"] == "user":
            model_history.append(ModelRequest(parts=[UserPromptPart(content=content)]))
        elif msg["role"] == "assistant":
            model_history.append(
                ModelResponse(parts=[TextPart(content=content)], usage=_recorded_usage(msg))
            )
        elif msg["role"] == "system":
            model_history.append(ModelRequest(parts=[SystemPromptPart(content=content)]))

    return model_history


def _recorded_usage(msg: HistoryMessage) -> RequestUsage:
    """What the provider was sent for the request this answer came out of.

    `context_used_tokens`, and deliberately not the `input_tokens` beside it in
    the same row. That column is a run's *whole* bill - every request of a
    hundred-step tool loop summed - and the anchor is a statement about **one**
    request. Anchored on a sum, a long turn would read as several times its own
    size and compact a history that fits comfortably, on every request, for ever.

    No output. The anchor's arithmetic is `input + output`, and what the last
    response itself cost is not recorded per request; zero undercounts by the
    length of one answer, which is a few hundred tokens and errs late. The next
    real response re-anchors it exactly.

    A zeroed usage where nothing was recorded, which is what `RequestUsage()`
    already is - the estimator only anchors on a response whose `input_tokens` is
    non-zero, so an unmeasured turn is passed over rather than treated as a
    request that cost nothing.
    """
    return RequestUsage(input_tokens=int(msg.get("context_used_tokens") or 0))
