"""Putting a capability's own model requests on the run's ledger.

A capability that runs a model the host agent did not ask for - a browse loop
deciding its next step, a browser sub-agent perceiving a page, a knowledge
search inferring its filters - spends money the `BudgetGuard` never sees. The guard wraps the *host*
agent's requests; these go out through an `Agent` the capability built, on a model
the capability chose, and arrive nowhere near it.

So the model is wrapped instead. :func:`~app.agents.capabilities.budget.record_ambient_usage`
books to whichever ledger the runner opened around the run, and is a no-op where
there is none - a preview, a test, the CLI. Shared rather than copied because two
capabilities wrapping a model two slightly different ways is how one of them
quietly stops counting.

The wrapper also refuses. A check made once before `agent.run` covers that run's
first request only: an output retry or a browse step is a further request, made
after the first one may have taken the run to its cap (agenticos#1808). Checking
here puts :func:`~app.agents.capabilities.budget.assert_ambient_budget` in front
of every request the wrapped model sends, streamed or not. Compaction books its
own way and does not pass through this wrapper.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import ModelRequestParameters, StreamedResponse
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import RunContext

from app.agents.capabilities.budget import assert_ambient_budget, record_ambient_usage


class MeteredModel(WrapperModel):
    """Refuses each request the run cannot afford, and books each one it makes.

    Refused before the wrapped request, so a run already at a cap sends nothing.
    Booked from the response, so a request that raised - which produced no usage -
    books nothing. Both are no-ops where no guard or ledger is active.
    """

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Make the wrapped request if the run can afford it, then book its usage.

        Raises:
            BudgetExceeded: A ceiling this run is under has been reached.
        """
        await assert_ambient_budget()
        response = await self.wrapped.request(messages, model_settings, model_request_parameters)
        record_ambient_usage(self.model_name or "unknown", response.usage)
        return response

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncGenerator[StreamedResponse, None]:
        """Stream the wrapped request if the run can afford it, then book its usage.

        Booked once the consumer has finished with the stream, from the usage it
        accumulated; a stream that raised books nothing, as a failed request does.

        Raises:
            BudgetExceeded: A ceiling this run is under has been reached.
        """
        await assert_ambient_budget()
        async with self.wrapped.request_stream(
            messages, model_settings, model_request_parameters, run_context
        ) as stream:
            yield stream
        record_ambient_usage(self.model_name or "unknown", stream.usage)
