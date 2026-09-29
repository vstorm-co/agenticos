"""`decide.score`: score a text against a rubric of levels, answered by Jev.

Level 0 is the first description, level 1 the next, and so on: a rubric whose
levels are not described is not a rubric, so every level says what it means.
The score is the nearest level; `position` is where between the levels Jev
placed the text. A confident score leaves by `out`, one below the floor by
`unsure`. See `app.workflows.nodes._decide`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.workflows.contracts.results import Completed, Failed, NodeResult
from app.workflows.nodes._decide import (
    DecisionConfig,
    DecisionInput,
    decide,
    failed,
    unsure_or,
)


class ScoreConfig(DecisionConfig):
    """The question, and what each level of the rubric means, lowest first."""

    levels: list[str] = Field(
        min_length=2,
        max_length=10,
        description="What each level means, from 0 upwards - 'not urgent', 'urgent', ...",
    )


class ScoreOutput(BaseModel):
    """The level, where between levels the text sat, and how sure Jev was."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    score: int
    position: float
    confidence: float
    unsure: bool


def routes(output: dict[str, Any] | None) -> frozenset[str]:
    """`out`, or `unsure` under the confidence floor."""
    return unsure_or("out", output)


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Score the text, and hand the level on."""
    if not isinstance(config, ScoreConfig) or not isinstance(node_input, DecisionInput):
        return failed("DECISION_NOT_CONFIGURED", "This step needs a question, levels and a text")
    rubric = {
        "anyOf": [
            {"const": level, "description": meaning} for level, meaning in enumerate(config.levels)
        ]
    }
    answered = await decide(config, node_input.text, rubric)
    if isinstance(answered, Failed):
        return answered
    score = int(answered.answer)
    return Completed[ScoreOutput](
        output=ScoreOutput(
            score=score,
            position=float(answered.score if answered.score is not None else score),
            confidence=answered.confidence,
            unsure=answered.confidence < config.min_confidence,
        )
    )
