"""Translate vendor human-input contracts into the initiating socket's live card."""

import json
from collections.abc import Mapping

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from app.agents.runtime_questions import (
    RuntimeChoice,
    RuntimeQuestion,
    RuntimeQuestionRequest,
    RuntimeQuestionResponse,
    RuntimeQuestionsCallback,
)


class _Option(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    id: str = Field(min_length=1, max_length=256)
    label: str = Field(min_length=1, max_length=256)


class _CursorQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    id: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=32000)
    options: list[_Option] = Field(min_length=1, max_length=128)
    allowMultiple: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def unique_options(self) -> _CursorQuestion:
        if len({option.id for option in self.options}) != len(self.options):
            raise ValueError("Cursor option IDs must be unique")
        return self


class _CursorQuestions(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    questions: list[_CursorQuestion] = Field(min_length=1, max_length=10)


async def ask(
    callback: RuntimeQuestionsCallback | None, name: str, questions: list[RuntimeQuestion]
) -> RuntimeQuestionResponse:
    request = RuntimeQuestionRequest(runtime_name=name, questions=questions)
    if callback is None:
        return RuntimeQuestionResponse(cancelled=True)
    return await callback(request)


async def cursor_questions(
    params: Mapping[str, object], callback: RuntimeQuestionsCallback | None
) -> dict[str, object]:
    parsed = _CursorQuestions.model_validate(params)
    questions = [
        RuntimeQuestion(
            id=question.id,
            header="Cursor",
            question=question.prompt,
            options=[RuntimeChoice(label=option.label) for option in question.options],
            multi_select=question.allowMultiple,
            allow_custom=False,
        )
        for question in parsed.questions
    ]
    response = await ask(callback, "Cursor", questions)
    if response.cancelled or len(response.answers) != len(questions):
        return {"outcome": {"outcome": "cancelled"}}
    answers: list[dict[str, object]] = []
    for question, answer in zip(parsed.questions, response.answers, strict=True):
        labels = set(answer.selected)
        picked = [option.id for option in question.options if option.label in labels]
        if answer.skipped or not picked or (not question.allowMultiple and len(picked) != 1):
            return {"outcome": {"outcome": "cancelled"}}
        answers.append({"questionId": question.id, "selectedOptionIds": picked})
    return {"outcome": {"outcome": "answered", "answers": answers}}


async def cursor_plan(
    params: Mapping[str, object], callback: RuntimeQuestionsCallback | None
) -> dict[str, object]:
    plan = params.get("plan")
    if not isinstance(plan, str) or not plan.strip():
        raise ValueError("A plan must contain the complete plan text")
    # Show the plan and its structured task/phase data before accepting either.
    body = json.dumps(
        {
            key: params[key]
            for key in ("name", "overview", "plan", "todos", "phases", "isProject")
            if key in params
        },
        ensure_ascii=False,
        indent=2,
    )
    response = await ask(
        callback,
        "Cursor",
        [
            RuntimeQuestion(
                id="plan",
                header="Cursor plan",
                question=body,
                options=[
                    RuntimeChoice(label="Approve plan", label_key="runtimeApprovePlan"),
                    RuntimeChoice(label="Reject plan", label_key="runtimeRejectPlan"),
                ],
                allow_custom=False,
            )
        ],
    )
    if response.cancelled or len(response.answers) != 1:
        return {"outcome": {"outcome": "cancelled"}}
    answer = response.answers[0]
    accepted = not answer.skipped and answer.selected == ["Approve plan"]
    return {"outcome": {"outcome": "accepted" if accepted else "rejected"}}


async def pi_dialog(
    params: Mapping[str, object], callback: RuntimeQuestionsCallback | None
) -> dict[str, object]:
    if params.get("secret") is True or params.get("isPassword") is True:
        raise ValueError("Secret input belongs to the program's own login")
    method = params.get("method")
    title = params.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("A Pi dialog needs its question text")
    choices: list[RuntimeChoice] = []
    if method == "select":
        options = params.get("options")
        if (
            not isinstance(options, list)
            or not options
            or any(not isinstance(option, str) for option in options)
        ):
            raise ValueError("Pi selection choices must be text")
        choices = [RuntimeChoice.model_validate({"label": option}) for option in options]
    elif method == "confirm":
        choices = [
            RuntimeChoice(label="Yes", label_key="runtimeYes"),
            RuntimeChoice(label="No", label_key="runtimeNo"),
        ]
    elif method not in {"input", "editor"}:
        raise ValueError("Unsupported Pi dialog")
    prefill = params.get("prefill")
    message = params.get("message")
    response = await ask(
        callback,
        "Pi",
        [
            RuntimeQuestion(
                id="dialog",
                header="Pi",
                question=title + (f"\n\n{message}" if isinstance(message, str) and message else ""),
                options=choices,
                allow_custom=method in {"input", "editor"},
                allow_empty=method in {"input", "editor"},
                multiline=method == "editor",
                initial_value=prefill if method == "editor" and isinstance(prefill, str) else None,
            )
        ],
    )
    if response.cancelled or len(response.answers) != 1 or response.answers[0].skipped:
        return {"cancelled": True}
    answer = response.answers[0]
    if method == "confirm":
        if answer.selected not in (["Yes"], ["No"]):
            return {"cancelled": True}
        return {"confirmed": answer.selected == ["Yes"]}
    if method == "select":
        if len(answer.selected) != 1 or answer.selected[0] not in {
            choice.label for choice in choices
        }:
            return {"cancelled": True}
        return {"value": answer.selected[0]}
    return {"value": answer.answer}


async def permission_question(
    params: Mapping[str, object], callback: RuntimeQuestionsCallback | None
) -> dict[str, object]:
    call = params.get("toolCall")
    if not isinstance(call, dict):
        raise TypeError("A permission question needs its content")
    pieces: list[str] = []
    for part in call.get("content", []):
        if (
            isinstance(part, dict)
            and isinstance(content := part.get("content"), dict)
            and isinstance(value := content.get("text"), str)
        ):
            pieces.append(value)
    options = params.get("options")
    if not isinstance(options, list):
        raise TypeError("A permission question needs options")
    offered = [
        option
        for option in options
        if isinstance(option, dict) and option.get("kind") == "allow_once"
    ]
    choices = [
        _Option.model_validate({"id": option.get("optionId"), "label": option.get("name")})
        for option in offered
    ]
    if len({choice.id for choice in choices}) != len(choices):
        raise ValueError("Kimi option IDs must be unique")
    response = await ask(
        callback,
        "Kimi Code",
        [
            RuntimeQuestion(
                id="question",
                header="Kimi Code",
                question="\n".join(pieces),
                options=[RuntimeChoice(label=choice.label) for choice in choices],
                allow_custom=False,
            )
        ],
    )
    if response.cancelled or len(response.answers) != 1:
        return {"outcome": {"outcome": "cancelled"}}
    answer = response.answers[0]
    if answer.skipped or len(answer.selected) != 1:
        return {"outcome": {"outcome": "cancelled"}}
    selected = next((choice for choice in choices if choice.label == answer.selected[0]), None)
    return (
        {"outcome": {"outcome": "selected", "optionId": selected.id}}
        if selected
        else {"outcome": {"outcome": "cancelled"}}
    )


class _GrokOption(RuntimeChoice):
    preview: str | None = Field(default=None, max_length=16000)


class _GrokQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    question: str = Field(min_length=1, max_length=16000)
    options: list[_GrokOption] = Field(default_factory=list, max_length=128)
    multiSelect: bool | None = Field(
        default=None, validation_alias=AliasChoices("multiSelect", "multi_select")
    )


class _GrokQuestions(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    questions: list[_GrokQuestion] = Field(min_length=1, max_length=10)


async def grok_questions(
    params: Mapping[str, object], callback: RuntimeQuestionsCallback | None
) -> dict[str, object]:
    parsed = _GrokQuestions.model_validate(params)
    if len({question.question for question in parsed.questions}) != len(parsed.questions):
        raise ValueError("Grok answer keys must be unambiguous")
    questions = [
        RuntimeQuestion(
            id=str(index),
            header="Grok",
            question=question.question
            + "".join(
                f"\n\n{option.label}:\n{option.preview}"
                for option in question.options
                if option.preview
            ),
            options=[
                RuntimeChoice(label=option.label, description=option.description)
                for option in question.options
            ],
            multi_select=question.multiSelect is True,
        )
        for index, question in enumerate(parsed.questions)
    ]
    response = await ask(callback, "Grok", questions)
    if response.cancelled or len(response.answers) != len(questions):
        return {"outcome": "cancelled"}
    answers: dict[str, list[str]] = {}
    annotations: dict[str, dict[str, str]] = {}
    for question, answer in zip(parsed.questions, response.answers, strict=True):
        if answer.skipped:
            continue
        offered = {option.label for option in question.options}
        if not set(answer.selected) <= offered or (
            not question.multiSelect and len(answer.selected) > 1
        ):
            return {"outcome": "cancelled"}
        if answer.selected:
            answers[question.question] = answer.selected
        if answer.answer:
            answers.setdefault(question.question, ["Other"])
            annotations.setdefault(question.question, {})["notes"] = answer.answer
        if len(answer.selected) == 1:
            option = next(
                option for option in question.options if option.label == answer.selected[0]
            )
            if option.preview:
                annotations.setdefault(question.question, {})["preview"] = option.preview
    return (
        {"outcome": "accepted", "answers": answers, "annotations": annotations}
        if answers
        else {"outcome": "cancelled"}
    )


async def muse_questions(
    params: Mapping[str, object], callback: RuntimeQuestionsCallback | None
) -> dict[str, object]:
    request = RuntimeQuestionRequest.model_validate(
        {"runtime_name": "Muse", "questions": params.get("questions")}
    )
    response = await ask(callback, "Muse", request.questions)
    return response.model_dump()
