"""Bind accounting to the profile that actually answers, before SDK aggregation."""

from collections.abc import AsyncGenerator
from contextlib import ExitStack, asynccontextmanager
from typing import Any
from uuid import UUID

from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RequestUsage

from app.agents.stream_usage import final_stream_usage
from app.schemas.token_pricing import TokenPricing


class ProfilePricingModel(WrapperModel):
    """Apply the selected profile's rates to streaming and ordinary responses.

    Each fallback has its own wrapper; equal provider/model IDs therefore cannot
    accidentally share a price. Native cost and integer counters survive SDK
    RunUsage aggregation, including free requests and invalid usage.
    """

    def __init__(self, wrapped: Model, pricing: TokenPricing, profile_id: UUID | None) -> None:
        super().__init__(wrapped)
        self.pricing = pricing
        self.profile_id = profile_id

    def apply(self, usage: RequestUsage) -> None:
        cost = self.pricing.cost(usage)
        usage.cost = cost
        if hasattr(usage, "provider_reported_requests"):
            setattr(usage, "provider_reported_requests", 0)  # noqa: B010 - overridden bills must not count twice
        # RequestUsage supports arbitrary serialized metadata and integer counters.
        setattr(usage, "profile_priced_requests", int(cost is not None))  # noqa: B010 - SDK usage counter
        incomplete = cost is None or usage.unmeasured_requests > 0
        setattr(usage, "profile_unpriced_requests", int(incomplete))  # noqa: B010 - SDK usage counter
        provenance = {
            "profile_id": str(self.profile_id) if self.profile_id else None,
            "rates": self.pricing.model_dump(mode="json"),
            "cost_usd": str(cost) if cost is not None else None,
        }
        setattr(usage, "profile_pricing", provenance)  # noqa: B010 - SDK serialized usage metadata

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        response = await self.wrapped.request(messages, model_settings, model_request_parameters)
        self.apply(response.usage)
        return response

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncGenerator[StreamedResponse]:
        # Provider wrappers finalize the original bill when their stream closes.
        # Run our finalizer after theirs, including on interrupted streams.
        with ExitStack() as finalizers:
            async with self.wrapped.request_stream(
                messages, model_settings, model_request_parameters, run_context
            ) as stream:
                finalizers.callback(self._finalize_stream, stream)
                yield stream

    def _finalize_stream(self, stream: StreamedResponse) -> None:
        self.apply(final_stream_usage(stream))


def catalog_token_pricing(provider: str, model: str) -> TokenPricing | None:
    """Indicative catalog rates; provider-reported bills are known only after use."""
    from app.agents.capabilities.budget import price_request

    usages = [
        RequestUsage(input_tokens=1),
        RequestUsage(output_tokens=1),
        RequestUsage(input_tokens=1, cache_read_tokens=1),
        RequestUsage(input_tokens=1, cache_write_tokens=1),
    ]
    prices = [price_request(usage, model, provider) for usage in usages]
    if any(price is None for price in prices):
        return None
    return TokenPricing.model_validate(
        dict(
            zip(
                ("input", "output", "cache_read", "cache_write"),
                [price * 1_000_000 if price is not None else None for price in prices],
                strict=True,
            )
        )
    )
