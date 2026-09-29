"""`decide.yes_no`: a yes-or-no question about a text, answered by Jev.

The answer leaves by the `yes` or the `no` port, or by `unsure` when Jev's
confidence is below the step's floor - so a branch acts only on an answer
somebody set a bar for. See `app.workflows.nodes._decide`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from app.workflows.contracts.results import Completed, Failed, NodeResult
from app.workflows.nodes._decide import (
    UNSURE_PORT,
    DecisionConfig,
    DecisionInput,
    decide,
    failed,
)


class YesNoOutput(BaseModel):
    """Jev's answer, and how sure it was - 0 is a coin flip, 1 is certain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    answer: bool
    confidence: float
    unsure: bool


def routes(output: dict[str, Any] | None) -> frozenset[str]:
    """`yes`, `no`, or `unsure` under the confidence floor."""
    if output is None:
        return frozenset()
    if output.get("unsure"):
        return frozenset({UNSURE_PORT})
    return frozenset({"yes" if output.get("answer") else "no"})


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Ask the question, and name the port the answer leaves by."""
    if not isinstance(config, DecisionConfig) or not isinstance(node_input, DecisionInput):
        return failed("DECISION_NOT_CONFIGURED", "This step needs a question, a key and a text")
    answered = await decide(config, node_input.text, {"type": "boolean"})
    if isinstance(answered, Failed):
        return answered
    return Completed[YesNoOutput](
        output=YesNoOutput(
            answer=bool(answered.answer),
            confidence=answered.confidence,
            unsure=answered.confidence < config.min_confidence,
        )
    )
