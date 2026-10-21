"""Approvals inside a call (#54, Q7).

A realtime session cannot pause for approval, so `HandleDeferredToolCalls` hands
each gated call to this bridge, which:

1. takes the call's `ParkedApproval` off the run's channel - by tool call id -
   so `finish()` does not write the row a second time (spec amendment 3);
2. writes the approval row at once, committed, with the id the channel
   allocated;
3. tells the person on the call - the tool, its exact arguments, and what they
   were heard to say, because the human approving is the only check on a
   mishearing ("Acme" heard as "Ahmad", spike §5);
4. waits up to 60 s for an `approval` frame on *this* socket. The queue's route
   refuses a live call's rows: nobody else can decide what this person is
   waiting on;
5. on approve, puts the grant in `channel.decided[tool_call_id]` and answers
   `ToolApproved`, so the gate runs exactly the shown arguments, once.

A member without `approvals:decide` is told plainly, and the tool is denied with
a reason the agent says aloud. Timeouts, hang-ups and cancellations expire the
row with no decider.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

import anyio
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import (
    DeferredToolRequests,
    DeferredToolResults,
    RunContext,
    ToolApproved,
    ToolDenied,
)

from app.agents.approval import ApprovalGranted
from app.agents.deps import AgentDeps
from app.core.permissions import AuthContext
from app.schemas.voice import (
    ApprovalRequiredFrame,
    ApprovalSettledFrame,
    ApprovalUnavailableFrame,
    ServerFrame,
)
from app.services.agent_runner import ApprovalChannel, ParkedApproval
from app.services.approvals import ApprovalService
from app.services.voice.transcript import SessionFactory

APPROVAL_TIMEOUT_SECONDS = 60

SendFrame = Callable[[ServerFrame], Awaitable[None]]
"""How the call's parts send a frame to the caller: the session's, which filters it first."""

_DENIED = "The person on the call declined this action. Say so and do not claim it happened."
_EXPIRED = "Nobody approved this action within a minute, so it did not run. Say so plainly."
_NOT_POSSIBLE = (
    "This action needs an approval that this caller cannot give by voice. Say so plainly, and "
    "suggest asking in text chat, where the request can wait for somebody who can approve it."
)
_NOT_POSSIBLE_NOTE = "Not decided: the caller may not approve tool calls."


@dataclass
class _Waiting:
    """One approval the call is waiting on.

    `future` resolves to the decision, or to `None` when nobody decided in time.
    `deciding` is set while a decision's row is being written: the timeout then
    waits for that write instead of expiring the row under it, so exactly one
    outcome wins and the row says what the tool did.
    """

    tool_call_id: str
    future: asyncio.Future[bool | None]
    deciding: bool = False


class VoiceApprovalBridge:
    """The `HandleDeferredToolCalls` handler of one call, and the socket side of its decisions."""

    def __init__(
        self,
        *,
        sessions: SessionFactory,
        decider: AuthContext | None,
        send: SendFrame,
        heard: Callable[[], str | None],
        timeout: float = APPROVAL_TIMEOUT_SECONDS,
    ) -> None:
        self._sessions = sessions
        self._decider = decider
        self._send = send
        self._heard = heard
        self._timeout = timeout
        self._channel: ApprovalChannel | None = None
        self._waiting: dict[str, _Waiting] = {}

    def refresh_decider(self, decider: AuthContext | None) -> None:
        """Who may decide from now on, as the heartbeat last read it: a lost
        `approvals:decide` stops the caller deciding mid-call."""
        self._decider = decider

    def attach(self, channel: ApprovalChannel) -> None:
        """The run's channel, known only once `prepare` built the agent this bridge is a part of."""
        self._channel = channel

    async def __call__(
        self, ctx: RunContext[AgentDeps], requests: DeferredToolRequests
    ) -> DeferredToolResults:
        """Settle each gated call in turn, as the session's deferred-call handler."""
        decisions: dict[str, ToolApproved | ToolDenied] = {}
        for call in requests.approvals:
            decisions[call.tool_call_id] = await self._one(call)
        return requests.build_results(approvals=decisions)

    def _take(self, tool_call_id: str) -> ParkedApproval | None:
        channel = self._channel
        if channel is None:
            return None
        parked = next((p for p in channel.requested if p.tool_call_id == tool_call_id), None)
        if parked is not None:
            channel.requested.remove(parked)
            channel.parked.pop(str(parked.approval_id), None)
        return parked

    async def _one(self, call: ToolCallPart) -> ToolApproved | ToolDenied:
        parked = self._take(call.tool_call_id)
        channel = self._channel
        if parked is None or channel is None:
            return ToolDenied(_EXPIRED)
        approval_id = str(parked.approval_id)
        async with self._sessions() as db:
            await ApprovalService(db).request(
                approval_id=parked.approval_id,
                organization_id=channel.organization_id,
                run_id=channel.run_id,
                agent_id=channel.agent_id,
                tool_id=parked.tool_name,
                tool_args=parked.tool_args,
            )
        if self._decider is None:
            await self._expire(channel, parked, note=_NOT_POSSIBLE_NOTE)
            await self._send(
                ApprovalUnavailableFrame(
                    type="approval_unavailable", tool=parked.tool_name, args=parked.tool_args
                )
            )
            return ToolDenied(_NOT_POSSIBLE)
        future: asyncio.Future[bool | None] = asyncio.get_running_loop().create_future()
        waiting = _Waiting(tool_call_id=call.tool_call_id, future=future)
        self._waiting[approval_id] = waiting
        try:
            await self._send(
                ApprovalRequiredFrame(
                    type="approval_required",
                    id=approval_id,
                    tool=parked.tool_name,
                    args=parked.tool_args,
                    said=self._heard(),
                    timeout_seconds=int(self._timeout),
                )
            )
            try:
                approved = await asyncio.wait_for(asyncio.shield(future), self._timeout)
            except TimeoutError:
                if waiting.deciding:
                    # A decision arrived in time and its row is being written: it wins.
                    approved = await future
                else:
                    future.set_result(None)
                    approved = None
        except asyncio.CancelledError:
            if not waiting.deciding and not future.done():
                future.set_result(None)
            with anyio.CancelScope(shield=True):
                await self._expire(channel, parked)
            raise
        finally:
            self._waiting.pop(approval_id, None)
        if approved is None:
            await self._expire(channel, parked)
            await self._send(
                ApprovalSettledFrame(type="approval_settled", id=approval_id, outcome="expired")
            )
            return ToolDenied(_EXPIRED)
        await self._send(
            ApprovalSettledFrame(
                type="approval_settled",
                id=approval_id,
                outcome="approved" if approved else "denied",
            )
        )
        if approved:
            channel.decided[call.tool_call_id] = ApprovalGranted(parked.tool_args)
            return ToolApproved()
        return ToolDenied(_DENIED)

    async def _expire(
        self, channel: ApprovalChannel, parked: ParkedApproval, *, note: str | None = None
    ) -> None:
        async with self._sessions() as db:
            await ApprovalService(db).expire_now(
                parked.approval_id, organization_id=channel.organization_id, note=note
            )

    async def decide(self, approval_id: str, *, approve: bool) -> bool:
        """A decision from this call's socket. `False` for an approval this call is not waiting on.

        `True` as well for one this call has already taken a decision on - a double
        click, or approve then deny: the first decision stands, and its
        `approval_settled` is still to come, so the second must not be told as expired.
        """
        waiting = self._waiting.get(approval_id)
        if waiting is not None and (
            waiting.deciding or (waiting.future.done() and waiting.future.result() is not None)
        ):
            return True
        if waiting is None or waiting.future.done() or self._decider is None:
            return False
        waiting.deciding = True
        try:
            async with self._sessions() as db:
                await ApprovalService(db).decide(
                    self._decider, UUID(approval_id), approved=approve, via_call=True
                )
        except BaseException:
            # The row did not take the decision, so the tool must not either: the
            # waiting call reads it as undecided and expires the row. Nothing else
            # resolves the future while `deciding` is set, so it is still open.
            waiting.future.set_result(None)
            raise
        waiting.future.set_result(approve)
        return True
