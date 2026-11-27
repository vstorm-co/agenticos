"""What a generation is estimated to cost, before anything is spent.

An estimate and nothing more: the prompt is measured at four characters a token
and every drafted case is assumed to take a fixed number of output tokens. The
budget is enforced by the runner before the model is called, never by this
number - which is shown so a person decides with a figure in front of them.
"""

import math
from decimal import Decimal

from pydantic_ai.usage import RequestUsage

from app.agents.capabilities.budget import price_request
from app.schemas.token_pricing import TokenPricing

CHARS_PER_TOKEN = 4
# The generator's own instructions and the output schema, on top of the prompt.
FIXED_INPUT_TOKENS = 1_500
OUTPUT_TOKENS_PER_CASE = 400


def estimate_tokens(prompt: str, cases: int) -> tuple[int, int]:
    """Estimated input and output tokens for one generation."""
    return (
        FIXED_INPUT_TOKENS + math.ceil(len(prompt) / CHARS_PER_TOKEN),
        cases * OUTPUT_TOKENS_PER_CASE,
    )


def estimate_cost(
    prompt: str,
    cases: int,
    *,
    model_name: str,
    provider: str | None,
    custom_pricing: TokenPricing | None = None,
) -> Decimal | None:
    """Estimated USD cost using profile rates first, or `None` without a known price."""
    input_tokens, output_tokens = estimate_tokens(prompt, cases)
    return price_request(
        RequestUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        model_name,
        provider,
        custom_pricing=custom_pricing,
    )
