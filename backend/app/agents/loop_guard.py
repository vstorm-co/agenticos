"""Tool-call loops caught while a run is still cheap to stop (#2086).

An agent sometimes calls the same tool with the same arguments again and again,
or goes round a short cycle of calls, and makes no progress. `max_steps` bounds
that already, but late: the budget is spent, and the run ends as a generic step
limit with no reason given.

Every agent gets this guard. It reads the run's own tool calls before each model
request. The first time it sees a loop - one call made `repeats` times in a row,
or a cycle of two or three calls gone round `cycles` times - it tells the model
it is looping and to change approach, on that request only, the way a system
reminder is added: the warning reaches the model and never enters the history.
If the calls after the warning loop again, the run stops with its own status,
`loop_stopped`, and a reason naming the tools - never their arguments, which may
carry what the agent read.

A call is the tool's name and its arguments, so reading ten different pages is
ten calls and no loop. Only this run's calls count - the guard notes each
response as it arrives rather than reading the history, which holds earlier
turns' calls and which a compaction may cut - and a person asking the same thing
twice is not the agent looping.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.tools import RunContext

from app.agents.deps import AgentDeps

if TYPE_CHECKING:
    from pydantic_ai.models import ModelRequestContext

LONGEST_CYCLE = 3
"""The longest cycle of distinct calls looked for. Longer ones are rarer than a
legitimate workflow that repeats, and `max_steps` still bounds them."""


class ToolLoopStopped(Exception):
    """A run stopped for looping after it was warned.

    A plain exception, not an `AppException`, for the reason `GuardrailBlocked`
    is: the runner maps it to its own `RunStatus`, and the message - tool names,
    never arguments - is safe to store on the run and show to the person.
    """


@dataclass(frozen=True)
class Loop:
    """What the guard saw: the calls that repeat, and how many times they did."""

    tools: tuple[str, ...]
    times: int

    def describe(self) -> str:
        names = " → ".join(f"`{tool}`" for tool in self.tools)
        if len(self.tools) == 1:
            return f"called {names} with the same arguments {self.times} times in a row"
        return f"went round the same calls ({names}) {self.times} times"


def _signature(part: ToolCallPart) -> tuple[str, str]:
    args = part.args
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return part.tool_name, args
    return part.tool_name, json.dumps(args, sort_keys=True, default=str)


def run_calls(messages: Sequence[ModelMessage], run_id: str | None) -> list[tuple[str, str]]:
    """This run's tool calls in order, each as its tool's name and its arguments."""
    return [
        _signature(part)
        for message in messages
        if isinstance(message, ModelResponse) and message.run_id == run_id
        for part in message.parts
        if isinstance(part, ToolCallPart)
    ]


def find_loop(calls: Sequence[tuple[str, str]], *, repeats: int, cycles: int) -> Loop | None:
    """The loop the calls end on, if they end on one.

    One call made `repeats` times in a row, or a cycle of two or three different
    calls made `cycles` times in a row - read from the end, so a loop the agent
    already left is not one it is in.
    """
    if len(calls) >= repeats and len(set(calls[-repeats:])) == 1:
        return Loop(tools=(calls[-1][0],), times=repeats)
    for period in range(2, LONGEST_CYCLE + 1):
        span = period * cycles
        if len(calls) < span:
            continue
        tail = calls[-span:]
        cycle = tail[:period]
        if len(set(cycle)) == period and all(
            tail[index] == cycle[index % period] for index in range(span)
        ):
            return Loop(tools=tuple(tool for tool, _ in cycle), times=cycles)
    return None


@dataclass
class LoopGuard(AbstractCapability[AgentDeps]):
    """Warns a run that loops on its tool calls, then stops it if it goes on.

    The run's calls are kept here, as each response arrives, rather than read
    back from the request: a compaction that summarises or slides the history
    removes the very responses a loop is made of, and a position in a history
    that shrinks means nothing a request later.
    """

    repeats: int = 4
    cycles: int = 3
    _calls: list[tuple[str, str]] = field(default_factory=list, init=False, repr=False)
    _warned_after: int | None = field(default=None, init=False, repr=False)
    """How many of the run's calls had been made when it was warned; only those
    after count towards stopping it."""

    async def for_run(self, ctx: RunContext[AgentDeps]) -> LoopGuard:
        """A guard of its own for each run.

        A delegate's built agent is cached and run once per delegation; on one
        shared instance, four separate delegations of the same lookup would read
        as one run calling it four times.
        """
        return LoopGuard(repeats=self.repeats, cycles=self.cycles)

    async def after_model_request(
        self,
        ctx: RunContext[AgentDeps],
        *,
        request_context: ModelRequestContext,
        response: ModelResponse,
    ) -> ModelResponse:
        """Note the calls this response asked for."""
        self._calls.extend(run_calls([response], response.run_id))
        return response

    async def before_model_request(
        self,
        ctx: RunContext[AgentDeps],
        request_context: ModelRequestContext,
    ) -> ModelRequestContext:
        """Warn on the first loop, and stop the run on the second.

        Raises:
            ToolLoopStopped: The calls after the warning looped again.
        """
        messages = request_context.messages
        # Only a request this run makes: a provider-resume turn ends on a
        # suspended response, which is echoed back verbatim - see
        # `SystemReminders.before_model_request`.
        if not messages or not isinstance(last := messages[-1], ModelRequest):
            return request_context
        since = self._calls[self._warned_after or 0 :]
        loop = find_loop(since, repeats=self.repeats, cycles=self.cycles)
        if loop is None:
            return request_context
        if self._warned_after is not None:
            raise ToolLoopStopped(
                f"Stopped: the agent {loop.describe()} after it was told it was looping."
            )
        self._warned_after = len(self._calls)
        warning = (
            f"<system-reminder>You have {loop.describe()}, and it is not getting you "
            "anywhere. Stop repeating it. Change approach: use what the calls already "
            "returned, try a different tool or different arguments, or answer with "
            "what you have and say what is missing.</system-reminder>"
        )
        tail = replace(last, parts=[*last.parts, UserPromptPart(content=warning)])
        return replace(request_context, messages=[*messages[:-1], tail])
