"""Translate Stav's billed amount into a request-local USD cost.

The SDK's response parser sees both final JSON and SSE events, before OpenAI's
usage mapper drops the currency and decimal amount. A model wrapper owns the
capture's lifetime, so concurrent runs and fallbacks cannot borrow each other's
cost. No exchange-rate service is called from an agent request.
"""

import logging
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import ModelRequestParameters, StreamedResponse
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RequestUsage

from app.core.config import settings

logger = logging.getLogger(__name__)


def _amount(value: object) -> Decimal | None:
    if not isinstance(value, (str, int, float, Decimal)) or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    return amount if amount.is_finite() and amount >= 0 else None


@dataclass
class _Capture:
    cost: Decimal | None = None
    currency: str | None = None

    def apply(self, usage: RequestUsage) -> None:
        if self.cost is None:
            return
        rate = settings.STAV_NOK_PER_USD if self.currency == "NOK" else None
        if self.currency == "USD":
            usd = self.cost
        elif self.currency == "NOK" and rate is not None:
            usd = self.cost / rate
        else:
            logger.warning(
                "Stav billed cost cannot be converted to USD; configure STAV_NOK_PER_USD for NOK"
            )
            return
        # RequestUsage explicitly supports arbitrary serialized usage fields.
        setattr(usage, "provider_reported_cost_usd", usd)  # noqa: B010 - SDK extension, absent from its static type
        usage.cost = usd
        # Numeric counters survive RequestUsage -> RunUsage aggregation; Decimal extras do not.
        setattr(usage, "provider_reported_requests", 1)  # noqa: B010 - SDK's supported extra usage counter
        provenance = {
            "provider": "stav",
            "amount": str(self.cost),
            "currency": self.currency,
            "cost_usd": str(usd),
            "nok_per_usd": str(rate) if rate is not None else None,
        }
        setattr(usage, "provider_reported_cost", provenance)  # noqa: B010 - SDK extension, absent from its static type


_active: ContextVar[_Capture | None] = ContextVar("stav_billed_cost", default=None)


def capture_stav_cost(data: object, headers: Mapping[str, str]) -> None:
    """Read only cost fields, from a response or an SSE event's nested response.

    Body totals supersede headers, including zero. Streaming usage is cumulative,
    so the latest reported total replaces earlier values rather than adding them.
    """
    capture = _active.get()
    if capture is None:
        return
    if isinstance(data, dict):
        nested = data.get("response")
        body = nested if isinstance(nested, dict) else data
        usage = body.get("usage")
        if isinstance(usage, dict):
            amount = _amount(usage.get("cost"))
            currency = usage.get("cost_currency")
            if amount is not None and isinstance(currency, str):
                capture.cost, capture.currency = amount, currency
                return
    if capture.cost is None:
        amount = _amount(headers.get("x-stav-cost"))
        currency = headers.get("x-stav-cost-currency")
        if amount is not None and currency is not None:
            capture.cost, capture.currency = amount, currency


class StavCostModel(WrapperModel):
    """Attach the request's billed cost before any budget or ambient meter sees it."""

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        capture = _Capture()
        token = _active.set(capture)
        try:
            response = await self.wrapped.request(
                messages, model_settings, model_request_parameters
            )
            capture.apply(response.usage)
            return response
        finally:
            _active.reset(token)

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncGenerator[StreamedResponse]:
        capture = _Capture()
        token = _active.set(capture)
        try:
            async with self.wrapped.request_stream(
                messages, model_settings, model_request_parameters, run_context
            ) as stream:
                try:
                    yield stream
                finally:
                    capture.apply(stream.usage)
        finally:
            _active.reset(token)
