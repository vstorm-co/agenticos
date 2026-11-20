"""OpenRouter's model, sent once more without reasoning a provider refused to take back.

A run that sends the model back - an output validator, a structured answer that
breaks its schema, a tool's `ModelRetry` - echoes the previous response, its
reasoning blocks included. Anthropic, behind OpenRouter, has refused such an echo
as changed ("`thinking` or `redacted_thinking` blocks in the latest assistant
message cannot be modified", or Azure's "The block is bound to a different
conversation"), and every upstream OpenRouter tried refused it alike, so the run
failed instead of getting its second answer. What changed the blocks is not
known: the echo Pydantic AI builds keeps their order, text and signature, and
the same providers accept it.

Such a request is sent once more with the latest response's reasoning left out,
which the providers accept. Only that one request: the run's history, and what
the recording model writes down, keep the response as it arrived.
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import replace
from typing import Any

from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse, ThinkingPart
from pydantic_ai.models import ModelRequestParameters, StreamedResponse
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import RunContext

logger = logging.getLogger(__name__)

_REFUSALS = ("cannot be modified", "bound to a different conversation")


def refused_reasoning(error: ModelHTTPError) -> bool:
    """Whether the provider refused the request over the reasoning it was sent back."""
    body = str(error.body)
    return error.status_code == 400 and "thinking" in body and any(r in body for r in _REFUSALS)


def without_latest_reasoning(messages: list[ModelMessage]) -> list[ModelMessage]:
    """A copy of `messages` whose last response carries no reasoning; `messages` is untouched."""
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, ModelResponse):
            parts = [part for part in message.parts if not isinstance(part, ThinkingPart)]
            return [*messages[:index], replace(message, parts=parts), *messages[index + 1 :]]
    return list(messages)


class ReasoningResendOpenRouterModel(OpenRouterModel):
    """`OpenRouterModel`, resending once without the reasoning a provider refused."""

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        try:
            return await super().request(messages, model_settings, model_request_parameters)
        except ModelHTTPError as error:
            if not refused_reasoning(error):
                raise
            self._log_resend()
        return await super().request(
            without_latest_reasoning(messages), model_settings, model_request_parameters
        )

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncGenerator[StreamedResponse]:
        # Only a refusal while the stream opens is resent: once its first event
        # is out, the caller has shown it, and a second answer would follow it.
        async with AsyncExitStack() as stack:
            try:
                stream = await stack.enter_async_context(
                    super().request_stream(
                        messages, model_settings, model_request_parameters, run_context
                    )
                )
            except ModelHTTPError as error:
                if not refused_reasoning(error):
                    raise
                self._log_resend()
                stream = await stack.enter_async_context(
                    super().request_stream(
                        without_latest_reasoning(messages),
                        model_settings,
                        model_request_parameters,
                        run_context,
                    )
                )
            yield stream

    def _log_resend(self) -> None:
        logger.warning(
            "%s refused the reasoning sent back to it; resending without it", self.model_name
        )
