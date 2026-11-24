"""Journal the one image request and its usage before SDK output validation."""

from typing import Any, Never

from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import RunContext

from app.services.workflow_execution import context
from app.services.workflow_media._errors import MediaOperationError
from app.services.workflow_media._journal import ImageReceipt, MediaJournal
from app.services.workflow_media._pricing import ImagePriceBasis, image_cost


class DurableImageModel(WrapperModel):
    def __init__(self, model: Model, journal: MediaJournal, basis: ImagePriceBasis) -> None:
        super().__init__(model)
        self.journal = journal
        self.basis = basis

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        # The committed transition refuses a second call even if a future SDK
        # attempts an output correction despite strict execution's retry cap.
        operation = await self.journal.start(context.current())
        response = await self.wrapped.request(messages, model_settings, model_request_parameters)
        # A synchronous image API names its response only when it answers. Journal
        # that id first, before usage and before the SDK validates any output, so
        # an interruption after the charge still leaves the provider's reference.
        if response.provider_response_id is not None:
            await self.journal.receipt(
                ImageReceipt(
                    provider=operation.provider,
                    api=operation.provider_api,
                    model=operation.model,
                    id=response.provider_response_id,
                )
            )
        await self.journal.cost(image_cost(self.basis, response))
        return response

    def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> Never:
        raise MediaOperationError(
            "MEDIA_STREAMING_REFUSED",
            "Workflow image generation requires its single journaled response",
        )
