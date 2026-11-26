"""Live questions from an owned runtime, without parking an in-flight native RPC."""

import unicodedata
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.agents.ask_user import QuestionChoice


class RuntimeChoice(QuestionChoice):
    label_key: (
        Literal["runtimeApprovePlan", "runtimeRejectPlan", "runtimeYes", "runtimeNo"] | None
    ) = None
    label: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=1024)

    @field_validator("label")
    @classmethod
    def visible_label(cls, value: str) -> str:
        if not value.strip() or not all(character.isprintable() for character in value):
            raise ValueError("Runtime choices require visible labels")
        return value


class RuntimeQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    multi_select: bool = False
    allow_custom: bool = True
    multiline: bool = False
    allow_empty: bool = False
    initial_value: str | None = Field(default=None, max_length=32000)
    max_answer_length: int = Field(default=32000, ge=1, le=32000)
    id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=32000)
    header: str | None = Field(default=None, max_length=120)
    options: list[RuntimeChoice] = Field(default_factory=list, max_length=128)
    min_selections: int | None = Field(default=None, ge=0, le=128)
    max_selections: int | None = Field(default=None, ge=1, le=128)

    @field_validator("question", "header")
    @classmethod
    def visible_text(cls, value: str | None) -> str | None:
        if value is not None and any(
            not character.isprintable() and character not in {"\n", "\t"} for character in value
        ):
            raise ValueError("Runtime questions require visible text")
        return value

    @model_validator(mode="after")
    def unambiguous_choices(self) -> RuntimeQuestion:
        labels = [
            " ".join(unicodedata.normalize("NFKC", choice.label).split()).casefold()
            for choice in self.options
        ]
        if len(labels) != len(set(labels)):
            raise ValueError("Runtime choices must be unambiguous")
        if self.min_selections is not None and self.min_selections > (
            self.max_selections if self.max_selections is not None else len(self.options)
        ):
            raise ValueError("Invalid runtime selection bounds")
        return self


class RuntimeQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    runtime_name: str = Field(min_length=1, max_length=120)
    questions: list[RuntimeQuestion] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def unique_ids(self) -> RuntimeQuestionRequest:
        if len({question.id for question in self.questions}) != len(self.questions):
            raise ValueError("Runtime question IDs must be unique")
        return self


class RuntimeAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    answer: str = Field(default="", max_length=32000)
    selected: list[Annotated[str, Field(max_length=256)]] = Field(
        default_factory=list, max_length=128
    )
    skipped: bool = Field(default=False, strict=True)


class RuntimeQuestionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answers: list[RuntimeAnswer] = Field(default_factory=list, max_length=10)
    cancelled: bool = False


RuntimeQuestionsCallback = Callable[[RuntimeQuestionRequest], Awaitable[RuntimeQuestionResponse]]


def normalize_runtime_answers(
    request: RuntimeQuestionRequest, raw: object
) -> RuntimeQuestionResponse:
    """Admit only the initiating person's bounded, offered or explicitly custom answers."""
    if not isinstance(raw, list) or len(raw) != len(request.questions):
        return RuntimeQuestionResponse(cancelled=True)
    try:
        answers = [RuntimeAnswer.model_validate(answer) for answer in raw]
    except ValidationError:
        return RuntimeQuestionResponse(cancelled=True)
    cleaned: list[RuntimeAnswer] = []
    for question, answer in zip(request.questions, answers, strict=True):
        offered = {option.label for option in question.options}
        chosen = list(dict.fromkeys(label for label in answer.selected if label in offered))
        if not question.multi_select:
            chosen = chosen[:1]
        elif len(chosen) < (
            question.min_selections if question.min_selections is not None else 1
        ) or len(chosen) > (
            question.max_selections
            if question.max_selections is not None
            else len(question.options)
        ):
            chosen = []
        typed = (
            (answer.answer if question.multiline else answer.answer.strip())
            if question.allow_custom and not answer.skipped
            else ""
        )
        if len(typed) > question.max_answer_length:
            typed = ""
            answer = RuntimeAnswer(skipped=True)
        accepted_empty = (
            (question.allow_custom and question.allow_empty)
            or (question.multi_select and question.min_selections == 0)
        ) and not answer.skipped
        cleaned.append(
            RuntimeAnswer(
                selected=chosen if not answer.skipped else [],
                answer=typed,
                skipped=answer.skipped or not (chosen or typed or accepted_empty),
            )
        )
    return RuntimeQuestionResponse(
        answers=cleaned, cancelled=all(answer.skipped for answer in cleaned)
    )
