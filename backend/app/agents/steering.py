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

from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.tools import RunContext

if TYPE_CHECKING:
    from pydantic_ai.models import ModelRequestContext
    from pydantic_ai_harness.guardrails import GuardrailResult

    from app.agents.deps import AgentDeps

__all__ = ["STEER_PREFIX", "Steer", "Steering", "SteeringInbox", "screen_steer"]

STEER_PREFIX = "[Added by the person while you were working - take it into account from here]"


class ChannelTurnStopped(Exception):
    """End a queued turn without another paid model request."""

    def __init__(self, reason: Literal["sender", "lease_lost"] = "sender") -> None:
        self.reason = reason
        super().__init__(
            "Stopped by the sender in the channel."
            if reason == "sender"
            else "The channel worker lost its execution lease; inspect existing actions before asking again."
        )


@dataclass
class SteerConsumption:
    """Shared receipt marker; it forbids release after any inbox takes the item."""

    consumed: bool = False


@dataclass
class Steer:
    """One message, and whether a model request has carried it yet."""

    text: str
    applied: bool = False
    accepted_queue_id: UUID | None = None
    consumption: SteerConsumption = field(default_factory=SteerConsumption)


@dataclass
class SteeringInbox:
    """The messages a person sent to the run they are watching.

    `on_applied` is told each one as it reaches the model, so the surface can
    show it in place in the turn.
    """

    on_applied: Callable[[Steer, str], Awaitable[None]] | None = None
    on_receipt_applied: Callable[[UUID, str], Awaitable[None]] | None = None
    poll: Callable[[AgentDeps], Awaitable[list[str]]] | None = None
    screen: Callable[[str], GuardrailResult] | None = None
    """The agent's input guardrail, set by the runner: a steer reaches the model
    from the second request on, past where the harness's input edge looks, so it
    is screened here - redacted, or the run refused - before it is appended."""
    _steers: list[Steer] = field(default_factory=list)

    _listeners: list[tuple[str, SteeringInbox]] = field(default_factory=list, repr=False)

    @contextmanager
    def listen(self, session: str) -> Generator[SteeringInbox]:
        """Give a coding session its own cursor over targeted corrections.

        `[session:api] ...` targets sessions named api. With a single active
        session, an unaddressed correction reaches it as before. With several,
        unaddressed corrections stay with the parent rather than changing the
        wrong task. The parent records the correction once when it continues.
        """
        child = SteeringInbox(screen=self.screen, on_receipt_applied=self.on_receipt_applied)
        for steer in self.unapplied_steers():
            target, words = _session_correction(steer.text)
            if target == session or (target is None and not self._listeners):
                child.add(
                    words,
                    accepted_queue_id=steer.accepted_queue_id,
                    consumption=steer.consumption,
                )
        listener = (session, child)
        self._listeners.append(listener)
        try:
            yield child
        finally:
            self._listeners = [entry for entry in self._listeners if entry is not listener]

    def add(
        self,
        text: str,
        *,
        accepted_queue_id: UUID | None = None,
        consumption: SteerConsumption | None = None,
    ) -> Steer:
        if accepted_queue_id is not None:
            existing = self.receipt(accepted_queue_id)
            if existing is not None:
                return existing
        steer = Steer(
            text=text,
            accepted_queue_id=accepted_queue_id,
            consumption=SteerConsumption() if consumption is None else consumption,
        )
        self._steers.append(steer)
        target, words = _session_correction(text)
        for session, listener in self._listeners:
            if target == session or (target is None and len(self._listeners) == 1):
                listener.add(
                    words,
                    accepted_queue_id=accepted_queue_id,
                    consumption=steer.consumption,
                )
        return steer

    def receipt(self, accepted_queue_id: UUID) -> Steer | None:
        """Find one receipt without using message text as an identity key."""
        return next(
            (steer for steer in self._steers if steer.accepted_queue_id == accepted_queue_id),
            None,
        )

    @property
    def has_active_listeners(self) -> bool:
        """Whether a child inbox may still consume a copy of one of these steers."""
        return bool(self._listeners)

    def take(self) -> list[Steer]:
        """Everything not yet handed to the model, marked as handed now."""
        waiting = [steer for steer in self._steers if not steer.applied]
        for steer in waiting:
            steer.applied = True
            steer.consumption.consumed = True
        return waiting

    async def take_screened(self) -> list[tuple[Steer, str]]:
        """Screen and durably fence every receipt before a consumer uses its text."""
        steers = self.take()
        screened = [screen_steer(self, steer.text) for steer in steers]
        if self.on_receipt_applied is not None:
            for steer, text in zip(steers, screened, strict=True):
                if steer.accepted_queue_id is not None:
                    await self.on_receipt_applied(steer.accepted_queue_id, text)
        return list(zip(steers, screened, strict=True))

    def unapplied_steers(self) -> list[Steer]:
        """This inbox's own cursor, independent from any child inbox cursor."""
        return [steer for steer in self._steers if not steer.applied]

    def unapplied(self) -> list[str]:
        """What arrived too late for any request - to be sent as a message of its own."""
        return [steer.text for steer in self._steers if not steer.applied]


def _session_correction(text: str) -> tuple[str | None, str]:
    """An explicit session address, or unaddressed text for the parent."""
    if text.startswith("[session:"):
        address, separator, words = text.partition("]")
        if separator and words.strip():
            return address.removeprefix("[session:"), words.lstrip()
    return None, text


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
        if inbox.poll is not None:
            for text in await inbox.poll(ctx.deps):
                inbox.add(text)
        screened = await inbox.take_screened()
        if not screened:
            return request_context
        # Screened once, and the screened words are what the transcript keeps
        # too: a redacted secret must not come back in the next turn's history.
        steers = [steer for steer, _text in screened]
        said = [text for _steer, text in screened]
        added = UserPromptPart(content="\n\n".join([STEER_PREFIX, *said]))
        # The persistent history and this request's own list are separate lists
        # (usually holding the same message), so each takes the words explicitly:
        # the history so later requests and the transcript keep them, the request
        # so this one carries them.
        if ctx.messages and isinstance(kept := ctx.messages[-1], ModelRequest):
            ctx.messages[-1] = replace(kept, parts=[*kept.parts, added])
        if inbox.on_applied is not None:
            for steer, text in zip(steers, said, strict=True):
                await inbox.on_applied(steer, text)
        tail = replace(last, parts=[*last.parts, added])
        return replace(request_context, messages=[*messages[:-1], tail])


def screen_steer(inbox: SteeringInbox, text: str) -> str:
    """The steer as the input guardrail leaves it; a blocked one raises, ending the run."""
    if inbox.screen is None:
        return text
    verdict = inbox.screen(text)
    return str(verdict.replacement) if verdict.action == "replace" else text
