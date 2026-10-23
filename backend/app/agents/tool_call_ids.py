"""Tool call ids that name one call per conversation (#2171).

A provider names each call it asks for, and some OpenAI-compatible servers count
them from zero on every response: the second turn's first call is `call_0` again.
Everything that outlives a turn is keyed by that id - a drawing and its pictures,
the revision that points back at it, an approval - so a reused id makes the later
call overwrite or vanish behind the earlier one.

The fix is at the source: an id the conversation has already used is renamed as
the response arrives, the same way in both places that see it first. The stream
renames it on the part's start event, before the console is told about the call;
:class:`UniqueToolCallIds` renames it on the finished response, for a run that
did not stream and for a part a later delta reverted. Both pick the same new id
for the same history, so the console and the transcript agree on it.
"""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.tools import RunContext

from app.agents.deps import AgentDeps

if TYPE_CHECKING:
    from pydantic_ai.models import ModelRequestContext


def used_call_ids(messages: Iterable[ModelMessage]) -> set[str]:
    """Every tool call id the history already holds."""
    return {
        part.tool_call_id
        for message in messages
        if isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, ToolCallPart)
    }


def fresh_call_id(call_id: str, used: set[str]) -> str:
    """`call_id`, or the first `call_id~N` the history has not used, recorded as used.

    Deterministic, so the stream and the finished response rename one call alike.
    """
    candidate, n = call_id, 1
    while candidate in used:
        n += 1
        candidate = f"{call_id}~{n}"
    used.add(candidate)
    return candidate


@dataclass
class UniqueToolCallIds(AbstractCapability[AgentDeps]):
    """Renames a call whose id the conversation has already used, as the response arrives."""

    async def after_model_request(
        self,
        ctx: RunContext[AgentDeps],
        *,
        request_context: ModelRequestContext,
        response: ModelResponse,
    ) -> ModelResponse:
        used = used_call_ids(request_context.messages)

        def renamed[Part](part: Part) -> Part:
            if not isinstance(part, ToolCallPart):
                return part
            fresh = fresh_call_id(part.tool_call_id, used)
            return part if fresh == part.tool_call_id else replace(part, tool_call_id=fresh)

        parts = [renamed(part) for part in response.parts]
        if all(new is old for new, old in zip(parts, response.parts, strict=True)):
            return response
        return replace(response, parts=parts)
