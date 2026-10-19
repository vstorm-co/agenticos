"""One path for a code-built auxiliary agent, metered and capped like its run.

Several capabilities write through an `Agent` they construct themselves rather
than through the one the run was built from: a system reminder writes a steering
line, and - on the branches that add them - the knowledge self-query and toolset
summariser write a query and a digest. Each such call used to get the same four
things wrong, because each built its own `Agent(ctx.model, ...)`:

- it never re-checked the org and agent caps, so it spent past a budget the
  request wrapper would have refused (agenticos#1808);
- it traced its prompt and output with content even when the run asked for
  `content="none"` (agenticos#1809);
- it ran on the provider's default `ModelSettings` rather than the run's, so a
  run's timeout, `max_tokens` and temperature did not reach it (agenticos#1810);
- it metered itself by a snapshot/delta over the shared `ctx.usage`, which
  double-counts under a concurrent fan-out (agenticos#1811).

:func:`run_ambient_agent` is the one place those four are handled, so a site
adopts them by calling it instead of building its own agent. The two knowledge
sites keep their own agent: each holds its nested run to a request limit of its
own, meters per response through `MeteredModel`, and lets a budget refusal reach
the runner rather than degrading - so they take only :func:`run_model_settings`
from here.
"""

from typing import Any, cast

from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import RunContext

from app.agents.capabilities.budget import (
    can_afford_ambient_call,
    metered_nested_run,
    record_ambient_usage,
    reserved_limits,
)
from app.agents.observability import auxiliary_model


class AmbientCallSkipped(Exception):
    """Signals that an auxiliary model call was not made because a cap was reached.

    Raised by :func:`run_ambient_agent` when the run has already spent to a
    budget ceiling, so the caller degrades to its own model-free fallback - a
    goal reanchor, an un-reduced result - rather than spending past the cap. Not
    an `AppException`: like :class:`~app.agents.capabilities.budget.BudgetExceeded`
    it lives inside an agent run and is caught by the capability that started the
    call, never surfaced to a route.
    """


def run_model_settings(ctx: RunContext[Any]) -> ModelSettings | None:
    """The run's model settings for an auxiliary call on a request-response model.

    `ctx.model_settings` widens to `RealtimeModelSettings` on a realtime session,
    which is a distinct `TypedDict` with no runtime tag to tell it apart from a
    `ModelSettings`. An auxiliary agent only ever runs on a request-response
    :class:`~pydantic_ai.models.Model` - the caller has already excluded a realtime
    run before asking - so the settings are a `ModelSettings` there, narrowed with
    a cast the caller's guard makes safe.
    """
    return cast(ModelSettings | None, ctx.model_settings)


async def run_ambient_agent[OutputT](
    ctx: RunContext[Any],
    *,
    output_type: type[OutputT],
    user_prompt: str,
    instructions: str | None = None,
    model: Model | None = None,
    model_settings: ModelSettings | None = None,
) -> OutputT:
    """Run a one-shot auxiliary agent for `ctx`, metered and capped like the run.

    Checks the run's caps first: at a ceiling it raises :class:`AmbientCallSkipped`
    rather than spending (agenticos#1808). Builds the agent on a content-free model
    when the run traces without content (agenticos#1809), runs it under the run's
    own `ModelSettings` (agenticos#1810), and meters its spend through a private
    copy of `ctx.usage` so a concurrent fan-out cannot double-count it
    (agenticos#1811). The nested run is held one request below the run's limit so
    the parent's already-approved request cannot be pushed past its cap.

    `model` and `model_settings` run the call on a model of its own rather than
    the run's - a run reviewer on a cheaper profile - with everything else the same:
    the caps checked first, the run's tracing, and the spend booked on the run's
    ledger, priced as that model.

    Raises:
        AmbientCallSkipped: The run has reached a budget cap; the caller falls back
            to its model-free path.
        TypeError: The run's model is not request-response (a realtime model), so it
            cannot run an auxiliary agent. The caller falls back the same way.
    """
    if not await can_afford_ambient_call():
        raise AmbientCallSkipped("The run has reached a budget cap")
    chosen = auxiliary_model(ctx, model)
    if not isinstance(chosen, Model):
        raise TypeError(f"{type(ctx.model).__name__} cannot run an auxiliary agent")
    agent = Agent[None, OutputT](chosen, instructions=instructions, output_type=output_type)
    # The run's own model prices under its name. A model of the call's own may sit
    # behind fallbacks, whose composite name no price list knows, so each response
    # is booked as the model and provider that actually answered it.
    run_model_name = (ctx.model.model_name or "unknown") if model is None else None
    with metered_nested_run(ctx.usage, run_model_name) as usage:
        result = await agent.run(
            user_prompt,
            usage=usage,
            usage_limits=reserved_limits(ctx.usage_limits),
            model_settings=run_model_settings(ctx) if model is None else model_settings,
        )
    if model is not None:
        for message in result.new_messages():
            if isinstance(message, ModelResponse):
                record_ambient_usage(
                    message.model_name or "unknown", message.usage, message.provider_name
                )
    return result.output
