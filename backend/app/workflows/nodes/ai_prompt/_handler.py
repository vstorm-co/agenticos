"""`ai.prompt`: ask one of the organization's models, and use its answer.

The plainest model step: instructions the step writes, a prompt bound from the
run, and text back - or an object, when `structured_output_schema` asks for one.
No tools, so nothing it does needs an approval. It runs as the step's own agent
(see `_model_step`), which is where its budget, cost and trace come from.
"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, checked_output_schema
from app.core.permissions import AuthContext
from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError
from app.workflows.nodes import _model_step

NAME = "Ask a model"


class AiPromptConfig(_model_step.ModelStepConfig):
    """The model, what it is told to do, and the answer's shape if not text."""

    instructions: str = Field(
        default="",
        max_length=20_000,
        json_schema_extra={"x-multiline": True},
        description="What the model is told to do with every prompt - its role and rules.",
    )
    structured_output_schema: dict[str, Any] | None = Field(
        default=None,
        description="The JSON Schema of an object to answer with. Empty answers in text.",
    )

    _a_schema = field_validator("structured_output_schema")(checked_output_schema)


class AiPromptInput(BaseModel):
    """What the model is asked."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: str = Field(min_length=1, max_length=_model_step.MAX_TEXT)


class AiPromptOutput(BaseModel):
    """The answer, as text and - when a schema asked for one - as an object."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    structured: dict[str, Any] | None = None
    agent_run_id: UUID


def _spec(config: AiPromptConfig) -> AgentSpec:
    return _model_step.spec_for(
        config,
        name=NAME,
        instructions=config.instructions or "Answer the prompt.",
        output_schema=config.structured_output_schema,
    )


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """Refuse a model the graph's author may not use."""
    if not isinstance(config, AiPromptConfig):
        return []
    return await _model_step.problems(db, ctx, _spec(config))


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    if not isinstance(config, AiPromptConfig) or not isinstance(node_input, AiPromptInput):
        return Failed(
            error=WorkflowError(
                code="MODEL_STEP_NOT_CONFIGURED", message="This step needs a model and a prompt"
            )
        )
    answer = await _model_step.ask(config, _spec(config), node_input.prompt)
    if isinstance(answer, Failed):
        return answer
    if config.structured_output_schema is not None and answer.structured is None:
        return Failed(
            error=WorkflowError(
                code="STRUCTURED_OUTPUT_MISMATCH",
                message="The model answered in text, not with an object",
            )
        )
    return Completed[AiPromptOutput](
        output=AiPromptOutput(
            text=answer.text, structured=answer.structured, agent_run_id=answer.agent_run_id
        )
    )
