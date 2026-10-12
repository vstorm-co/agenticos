"""What a person adds to a task while the agent is still working on it (#2087).

A correction sent mid-run - "use the EU numbers" - used to wait for the turn to
end, by which time the agent had finished the wrong thing. The surface puts it in
the run's `SteeringInbox` instead, and `Steering` hands whatever has arrived to
the model at its next request, as the person's own words appended to that
request. The agent adjusts course without starting over, and the transcript says
where the correction arrived.

A message that arrives after the agent's last request has nothing left to steer.
It stays unapplied, and the surface sends it as an ordinary message once the turn
is over rather than losing it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.tools import RunContext

if TYPE_CHECKING:
    from pydantic_ai.models import ModelRequestContext

    from app.agents.deps import AgentDeps

__all__ = ["Steer", "Steering", "SteeringInbox"]

_PREFIX = "[Added by the person while you were working - take it into account from here]"


@dataclass
class Steer:
    """One message, and whether a model request has carried it yet."""

    text: str
    applied: bool = False


@dataclass
class SteeringInbox:
    """The messages a person sent to the run they are watching.

    `on_applied` is told each one as it reaches the model, so the surface can
    show it in place in the turn.
    """

    on_applied: Callable[[str], Awaitable[None]] | None = None
    _steers: list[Steer] = field(default_factory=list)

    def add(self, text: str) -> Steer:
        steer = Steer(text=text)
        self._steers.append(steer)
        return steer

    def take(self) -> list[Steer]:
        """Everything not yet handed to the model, marked as handed now."""
        waiting = [steer for steer in self._steers if not steer.applied]
        for steer in waiting:
            steer.applied = True
        return waiting

    def unapplied(self) -> list[str]:
        """What arrived too late for any request - to be sent as a message of its own."""
        return [steer.text for steer in self._steers if not steer.applied]


class Steering(AbstractCapability["AgentDeps"]):
    """Hands the person's mid-run messages to the model at its next request.

    On every agent, like the budget, and a no-op without an inbox - which is every
    surface but the ones somebody is watching. Written into the run's history,
    not only into this request: the model must keep seeing the correction on the
    requests after this one, and the transcript must hold it.
    """

    async def before_model_request(
        self,
        ctx: RunContext[AgentDeps],
        request_context: ModelRequestContext,
    ) -> ModelRequestContext:
        inbox = ctx.deps.steering
        if inbox is None:
            return request_context
        messages = request_context.messages
        # Only onto a real request: a provider-resume tail is a suspended
        # response echoed back verbatim, and nothing may be added to it.
        if not messages or not isinstance(last := messages[-1], ModelRequest):
            return request_context
        steers = inbox.take()
        if not steers:
            return request_context
        added = UserPromptPart(content="\n\n".join([_PREFIX, *(steer.text for steer in steers)]))
        # The persistent history and this request's own list are separate lists
        # (usually holding the same message), so each takes the words explicitly:
        # the history so later requests and the transcript keep them, the request
        # so this one carries them.
        if ctx.messages and isinstance(kept := ctx.messages[-1], ModelRequest):
            ctx.messages[-1] = replace(kept, parts=[*kept.parts, added])
        if inbox.on_applied is not None:
            for steer in steers:
                await inbox.on_applied(steer.text)
        tail = replace(last, parts=[*last.parts, added])
        return replace(request_context, messages=[*messages[:-1], tail])
