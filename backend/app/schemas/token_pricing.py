"""Flat prices per million normalized tokens, independent of model identity."""

from collections.abc import Mapping
from decimal import Decimal
from typing import Annotated

from pydantic import ConfigDict, Field
from pydantic_ai.usage import RequestUsage, RunUsage

from app.core.currency import CurrencyCode, to_usd
from app.schemas.base import BaseSchema

TokenRate = Annotated[Decimal, Field(ge=0, le=1_000_000, allow_inf_nan=False)]


class TokenPricing(BaseSchema):
    """A complete override; omitted cache rates inherit input, including zero.

    Null on a model profile selects automatic pricing. Rates use the selected currency per
    million tokens. SDK input counts include cached tokens, which are subtracted
    before applying the ordinary input rate.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    currency: CurrencyCode = "USD"
    input: TokenRate
    output: TokenRate
    cache_read: TokenRate | None = None
    cache_write: TokenRate | None = None

    def cost(self, usage: RequestUsage | RunUsage) -> Decimal | None:
        """Price measured tokens, retaining a subtotal when some usage is missing."""
        counts = (
            usage.input_tokens,
            usage.output_tokens,
            usage.cache_read_tokens,
            usage.cache_write_tokens,
        )
        if any(count < 0 for count in counts) or (usage.unmeasured_requests and not any(counts)):
            return None
        ordinary = usage.input_tokens - usage.cache_read_tokens - usage.cache_write_tokens
        if ordinary < 0:
            return None
        read = self.input if self.cache_read is None else self.cache_read
        write = self.input if self.cache_write is None else self.cache_write
        return (
            ordinary * self.input
            + usage.output_tokens * self.output
            + usage.cache_read_tokens * read
            + usage.cache_write_tokens * write
        ) / 1_000_000

    def usd_cost(
        self, usage: RequestUsage | RunUsage, rates: Mapping[str, Decimal] | None = None
    ) -> Decimal | None:
        amount = self.cost(usage)
        return (
            None
            if amount is None
            else to_usd(amount, self.currency, rates if rates is not None else {"USD": Decimal(1)})
        )
