"""`ai.extract`: pull the fields a schema names out of a text, as an object.

The step's `schema` is the object it hands on - an invoice's number, total and
due date out of an email, a lead's company and size out of a form. The model is
told to leave out what the text does not say rather than guess, and its answer
is the object of that shape or the step fails.
"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, checked_output_schema
from app.core.permissions import AuthContext
from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError
from app.workflows.nodes import _model_step

NAME = "Extract data"
_INSTRUCTIONS = (
    "Extract the fields the answer's schema asks for from the text you are given. "
    "Take each value from the text as written; leave a field out when the text does "
    "not say it, and never guess one."
)


class AiExtractConfig(_model_step.ModelStepConfig):
    """The model, the object to extract, and anything the model should know."""

    output_schema: dict[str, Any] = Field(
        title="Fields to extract",
        description="The JSON Schema of the object to extract.",
    )
    instructions: str = Field(
        default="",
        max_length=5_000,
        json_schema_extra={"x-multiline": True},
        description="Anything else the model should know, such as a date format.",
    )

    _a_schema = field_validator("output_schema")(checked_output_schema)


class AiExtractInput(BaseModel):
    """The text to read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1, max_length=_model_step.MAX_TEXT)


class AiExtractOutput(BaseModel):
    """The object extracted, and the run that extracted it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    data: dict[str, Any]
    agent_run_id: UUID


def _spec(config: AiExtractConfig) -> AgentSpec:
    instructions = _INSTRUCTIONS
    if config.instructions:
        instructions += f"\n\n{config.instructions}"
    return _model_step.spec_for(
        config, name=NAME, instructions=instructions, output_schema=config.output_schema
    )


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """Refuse a model the graph's author may not use."""
    if not isinstance(config, AiExtractConfig):
        return []
    return await _model_step.problems(db, ctx, _spec(config))


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    if not isinstance(config, AiExtractConfig) or not isinstance(node_input, AiExtractInput):
        return Failed(
            error=WorkflowError(
                code="MODEL_STEP_NOT_CONFIGURED",
                message="This step needs a model, the fields to extract and a text",
            )
        )
    answer = await _model_step.ask(config, _spec(config), node_input.text)
    if isinstance(answer, Failed):
        return answer
    if answer.structured is None:
        return Failed(
            error=WorkflowError(
                code="STRUCTURED_OUTPUT_MISMATCH",
                message="The model answered in text, not with the fields",
            )
        )
    return Completed[AiExtractOutput](
        output=AiExtractOutput(data=answer.structured, agent_run_id=answer.agent_run_id)
    )
