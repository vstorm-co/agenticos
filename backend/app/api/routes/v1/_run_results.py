"""What a continued run answers with, decided in one place.

Two routes continue a parked run - the resume after its approvals were decided,
and the answer to the questions it asked (#2064) - and a surface draws either the
same way, so the response is built here rather than twice.
"""

from app.core.permissions import AuthContext
from app.schemas.agent import AgentRunResult, RunStep, SettledCall
from app.services.agent_runner import AgentRunnerService, RunSegment


async def run_result(
    service: AgentRunnerService, ctx: AuthContext, segment: RunSegment
) -> AgentRunResult:
    """The continuation, with what it did and what it is waiting on now."""
    run = segment.run
    return AgentRunResult(
        run_id=run.id,
        output=segment.output,
        status=run.status,
        cost_usd=run.cost_usd,
        cost_is_partial=run.cost_is_partial,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        # What the continuation actually did. Nothing else carries it: the run
        # executes inside this request rather than on the socket the conversation
        # streams, so a caller given only the answer had to draw the second half
        # of a turn out of nothing.
        steps=[
            RunStep(
                tool_call_id=call.tool_call_id,
                tool_name=call.tool_name,
                args=call.args,
                result=call.result,
            )
            for call in segment.tool_calls
        ],
        # And what the approved call - or the answered question - returned. It
        # belongs to a step the caller drew before the run parked, so it updates
        # that step rather than adding one.
        settled=[
            SettledCall(tool_call_id=tool_call_id, result=result)
            for tool_call_id, result in segment.settled.items()
        ],
        # Empty unless the continuation stopped again, which it does whenever the
        # agent reaches a second gated call or asks a second question. Without
        # them a caller was told the run is still waiting and given nothing to do.
        parked=await service.parked_calls(ctx, run),
        questions=await service.parked_questions(ctx, run),
    )
