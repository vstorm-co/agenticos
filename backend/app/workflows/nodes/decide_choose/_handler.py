"""`decide.choose`: pick one of a list of options for a text, answered by Jev.

The options are the step's own, so the answer is always one of them - Jev
cannot return anything else. A confident pick leaves by `out`, carrying the
option and the whole distribution; one below the floor leaves by `unsure`.
See `app.workflows.nodes._decide`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.workflows.contracts.results import Completed, Failed, NodeResult
from app.workflows.nodes._decide import (
    DecisionConfig,
    DecisionInput,
    decide,
    failed,
    unsure_or,
)

MAX_OPTIONS = 255
"""Jev's own ceiling on one pick-one question."""


class DecisionOption(BaseModel):
    """One answer the step allows, and what it means when that is not obvious."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: str = Field(min_length=1, max_length=200)
    description: str | None = Field(
        default=None,
        max_length=1000,
        description="What this option means, in a line - Jev reads it alongside the option",
    )


class ChooseConfig(DecisionConfig):
    """The question, and the options it is answered from."""

    options: list[DecisionOption] = Field(min_length=2, max_length=MAX_OPTIONS)

    @model_validator(mode="after")
    def _distinct(self) -> ChooseConfig:
        values = [option.value for option in self.options]
        if len(set(values)) != len(values):
            raise ValueError("Two options have the same value")
        return self


class ChooseOutput(BaseModel):
    """The option picked, how sure Jev was, and the chance it gave each option."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    choice: str
    confidence: float
    probabilities: dict[str, float] = Field(default_factory=dict)
    unsure: bool


def routes(output: dict[str, Any] | None) -> frozenset[str]:
    """`out`, or `unsure` under the confidence floor."""
    return unsure_or("out", output)


def _answer(options: list[DecisionOption]) -> dict[str, Any]:
    return {
        "anyOf": [
            {
                "const": option.value,
                **({"description": option.description} if option.description else {}),
            }
            for option in options
        ]
    }


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Ask which option fits, and hand the pick on."""
    if not isinstance(config, ChooseConfig) or not isinstance(node_input, DecisionInput):
        return failed("DECISION_NOT_CONFIGURED", "This step needs a question, options and a text")
    answered = await decide(config, node_input.text, _answer(config.options))
    if isinstance(answered, Failed):
        return answered
    return Completed[ChooseOutput](
        output=ChooseOutput(
            choice=str(answered.answer),
            confidence=answered.confidence,
            probabilities=answered.probabilities,
            unsure=answered.confidence < config.min_confidence,
        )
    )
