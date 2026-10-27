"""`ai.classify`: put a text in one of the step's categories, and branch on it.

Each category is a named way out with a sentence saying what belongs in it; the
model picks exactly one, or `other` when none fits, and says why in a sentence.
The answer is asked for as an object whose `category` is an enum of the names,
so a model cannot invent a branch the graph has no wire for. Like `logic.switch`,
the chosen category is part of the stored output and `routes` reads it back.

**Confidence.** With `min_confidence` set, the model is also asked how sure it is
that the category is right, as a number from 0 to 1. That is the model's own
report, not a probability and not calibrated: a model tends to say 0.8 to 0.95
whatever it knows, so choose the minimum by looking at real answers. Below the
minimum the step leaves by its `unsure` port, as `decide.*` does, with the
category still on the output; at the minimum it leaves by the category. An
answer without a number never leaves by `unsure`. Without a minimum nothing is
asked, so the prompt, the answer's schema and the output's `confidence` (null)
are what they were before the field existed.
"""

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.permissions import AuthContext
from app.workflows.contracts.definition import Port
from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError
from app.workflows.nodes import _model_step
from app.workflows.nodes._decide import UNSURE_PORT, unsure_or

NAME = "Classify"
OTHER = "other"
MAX_CATEGORIES = 20
_RESERVED = frozenset({"in", OTHER})


class Category(BaseModel):
    """One way out, and what belongs in it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$", description="The branch's port id")
    description: str = Field(
        min_length=1, max_length=500, description="What belongs in this category"
    )


class AiClassifyConfig(_model_step.ModelStepConfig):
    """The categories, in order, and anything else the model should know."""

    categories: tuple[Category, ...] = Field(min_length=1, max_length=MAX_CATEGORIES)
    instructions: str = Field(
        default="",
        max_length=5_000,
        json_schema_extra={"x-multiline": True},
        description="Anything else the model should weigh, such as which category wins a tie.",
    )

    min_confidence: float | None = Field(
        default=None,
        ge=0,
        le=1,
        title="Minimum confidence",
        description=(
            "Below this the step leaves by its unsure port instead of by the category. "
            "Empty, it always leaves by the category."
        ),
    )

    @model_validator(mode="after")
    def _distinct_names(self) -> Self:
        names = [category.name for category in self.categories]
        if len(set(names)) != len(names):
            raise ValueError("Each category needs a name of its own")
        if _RESERVED & set(names):
            raise ValueError("A category cannot be called 'in' or 'other'")
        if self.min_confidence is not None and UNSURE_PORT in names:
            raise ValueError(
                f"A category cannot be called '{UNSURE_PORT}' when the step has a minimum confidence"
            )
        return self


class AiClassifyInput(BaseModel):
    """The text to classify."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1, max_length=_model_step.MAX_TEXT)


class AiClassifyOutput(BaseModel):
    """The category chosen, why, and the text passed on unchanged.

    `confidence` is filled in only when the step has a `min_confidence`, and `unsure`
    is true when it fell below that minimum, so the step left by its `unsure` port.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: str
    reason: str
    text: str
    confidence: float | None = Field(
        default=None,
        description=(
            "The model's own estimate, from 0 to 1, that the category is right. "
            "Its report, not a measured probability. Null when it gave none."
        ),
    )
    unsure: bool = Field(
        default=False,
        description="Whether the confidence was below the step's minimum, so the step left by unsure.",
    )


STATIC_PORTS = (
    Port(id="in", label="In", kind="input", schema=None),
    Port(id=OTHER, label="Other", kind="output", schema=AiClassifyOutput),
)


def ports_for(config: BaseModel | None) -> tuple[Port, ...]:
    """`in`, one output per category in order, `other`, and `unsure` with a minimum."""
    categories = config.categories if isinstance(config, AiClassifyConfig) else ()
    unsure = (
        (Port(id=UNSURE_PORT, label="Unsure", kind="output", schema=AiClassifyOutput),)
        if isinstance(config, AiClassifyConfig) and config.min_confidence is not None
        else ()
    )
    return (
        STATIC_PORTS[0],
        *(
            Port(id=category.name, label=category.name, kind="output", schema=AiClassifyOutput)
            for category in categories
        ),
        STATIC_PORTS[1],
        *unsure,
    )


def routes(output: dict[str, Any] | None) -> frozenset[str]:
    """The one port the stored output chose: `unsure`, else its category."""
    category = (output or {}).get("category")
    return unsure_or(category, output) if isinstance(category, str) else frozenset()


def _spec(config: AiClassifyConfig) -> AgentSpec:
    names = [category.name for category in config.categories]
    listed = "\n".join(f"- {c.name}: {c.description}" for c in config.categories)
    instructions = (
        "Classify the text you are given into exactly one of these categories:\n"
        f"{listed}\n"
        f"If none of them fits, answer {OTHER}. Give the reason in one sentence."
    )
    properties: dict[str, Any] = {
        "category": {"type": "string", "enum": [*names, OTHER]},
        "reason": {"type": "string"},
    }
    required = ["category", "reason"]
    if config.min_confidence is not None:
        instructions += (
            " Then say how sure you are that the category is right,"
            " as a number from 0 (a guess) to 1 (certain)."
        )
        properties["confidence"] = {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": (
                "How sure you are that the category is right, from 0 (a guess) to 1 (certain)."
            ),
        }
        required.append("confidence")
    if config.instructions:
        instructions += f"\n\n{config.instructions}"
    return _model_step.spec_for(
        config,
        name=NAME,
        instructions=instructions,
        output_schema={"type": "object", "properties": properties, "required": required},
    )


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """Refuse a model the graph's author may not use."""
    if not isinstance(config, AiClassifyConfig):
        return []
    return await _model_step.problems(db, ctx, _spec(config))


def _confidence(config: AiClassifyConfig, structured: dict[str, Any]) -> float | None:
    """The model's reported confidence; `None` without a minimum or without a number."""
    value = structured.get("confidence")
    if config.min_confidence is None or isinstance(value, bool):
        return None
    return float(value) if isinstance(value, int | float) else None


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    if not isinstance(config, AiClassifyConfig) or not isinstance(node_input, AiClassifyInput):
        return Failed(
            error=WorkflowError(
                code="MODEL_STEP_NOT_CONFIGURED",
                message="This step needs a model, categories and a text",
            )
        )
    answer = await _model_step.ask(config, _spec(config), node_input.text)
    if isinstance(answer, Failed):
        return answer
    chosen = (answer.structured or {}).get("category")
    allowed = {category.name for category in config.categories} | {OTHER}
    if chosen not in allowed:
        return Failed(
            error=WorkflowError(
                code="STRUCTURED_OUTPUT_MISMATCH",
                message="The model did not answer with one of the categories",
            )
        )
    confidence = _confidence(config, answer.structured or {})
    return Completed[AiClassifyOutput](
        output=AiClassifyOutput(
            category=str(chosen),
            reason=str((answer.structured or {}).get("reason", "")),
            text=node_input.text,
            confidence=confidence,
            unsure=(
                config.min_confidence is not None
                and confidence is not None
                and confidence < config.min_confidence
            ),
        )
    )
