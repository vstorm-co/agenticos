"""`ai.rewrite`: summarize, translate or rewrite a text.

Three everyday jobs that need nothing but the text and a sentence of direction,
offered as one step with a task rather than three near-identical ones. The
step's settings become the model's instructions; the text is the prompt.
"""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.permissions import AuthContext
from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError
from app.workflows.nodes import _model_step

NAME = "Summarize or translate"

Task = Literal["summarize", "translate", "rewrite"]
Length = Literal["short", "medium", "long"]

_LENGTHS: dict[str, str] = {
    "short": "in two or three sentences",
    "medium": "in one or two paragraphs",
    "long": "covering every point that matters, in as many paragraphs as it takes",
}


class AiRewriteConfig(_model_step.ModelStepConfig):
    """Which job, and how it should come out."""

    task: Task = Field(default="summarize", description="What to do with the text.")
    language: str | None = Field(
        default=None,
        max_length=64,
        description="The language to answer in - required to translate, optional otherwise.",
    )
    length: Length = Field(default="medium", description="How long a summary should be.")
    style: str = Field(
        default="",
        max_length=1_000,
        description="How it should read, such as 'formal' or 'for a customer'.",
    )

    @model_validator(mode="after")
    def _a_language_to_translate_into(self) -> Self:
        if self.task == "translate" and not self.language:
            raise ValueError("Say which language to translate into")
        return self


class AiRewriteInput(BaseModel):
    """The text to work on."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1, max_length=_model_step.MAX_TEXT)


class AiRewriteOutput(BaseModel):
    """The text that came out."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    agent_run_id: UUID


def _instructions(config: AiRewriteConfig) -> str:
    if config.task == "summarize":
        lines = [f"Summarize the text you are given {_LENGTHS[config.length]}."]
    elif config.task == "translate":
        lines = [f"Translate the text you are given into {config.language}, keeping its meaning."]
    else:
        lines = ["Rewrite the text you are given, keeping everything it says."]
    if config.language and config.task != "translate":
        lines.append(f"Answer in {config.language}.")
    if config.style:
        lines.append(f"Style: {config.style}.")
    lines.append("Answer with the result alone, nothing before or after it.")
    return " ".join(lines)


def _spec(config: AiRewriteConfig) -> AgentSpec:
    return _model_step.spec_for(config, name=NAME, instructions=_instructions(config))


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """Refuse a model the graph's author may not use."""
    if not isinstance(config, AiRewriteConfig):
        return []
    return await _model_step.problems(db, ctx, _spec(config))


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    if not isinstance(config, AiRewriteConfig) or not isinstance(node_input, AiRewriteInput):
        return Failed(
            error=WorkflowError(
                code="MODEL_STEP_NOT_CONFIGURED", message="This step needs a model and a text"
            )
        )
    answer = await _model_step.ask(config, _spec(config), node_input.text)
    if isinstance(answer, Failed):
        return answer
    return Completed[AiRewriteOutput](
        output=AiRewriteOutput(text=answer.text, agent_run_id=answer.agent_run_id)
    )
