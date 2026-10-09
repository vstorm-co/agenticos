"""Asking the person who is sitting there.

An agent can pause a run to put questions to the user and resume with their
answers. The pause and resume live in the WebSocket session, which owns the
socket; what lives here is the question schema and the rendering of the
collected answers back into something the model reads.

Deliberately not a capability. Capabilities are switched on per agent, and this
is not a property of the agent at all - it is whether the *surface* running it
can hold a question open. A Slack webhook and a scheduled run cannot, which is
why `AgentDeps.ask_user` is optional and tools that need it must refuse when
it is absent rather than proceed unattended.
"""

from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai_harness.ask_user import AskUserAnswer, AskUserRequest, AskUserResponse
from subagents_pydantic_ai import current_subagent_state

MAX_QUESTIONS = 10


class QuestionChoice(BaseModel):
    """One answer a question offers."""

    label: str = Field(description="What the person picks, in a few words.")
    description: str | None = Field(
        default=None, description="What picking it means, shown under the label."
    )


class QuestionItem(BaseModel):
    """One question to put to the user, as the console's question card draws it.

    The same shape for a delegate's one free-text question (`ask_parent`) and for
    the `ask_user` capability's batch of multiple-choice ones (#2064), so the
    surface keeps a single card and a single frame for both.
    """

    question: str = Field(description="The question text.")
    header: str | None = Field(
        default=None, description="A short label for the question, shown as a chip."
    )
    options: list[QuestionChoice] = Field(
        default_factory=list,
        description="Optional suggested answers, shown as choices.",
    )
    multi_select: bool = Field(default=False, description="Whether several options may be picked.")
    allow_custom: bool = Field(
        default=True,
        description="Whether the user may type a free-form answer instead of picking an option.",
    )


def wire_questions(request: AskUserRequest) -> list[dict[str, Any]]:
    """The `ask_user` capability's questions, as the surface's question frame carries them."""
    return [
        QuestionItem(
            question=question.question,
            header=question.header,
            options=[
                QuestionChoice(label=option.label, description=option.description)
                for option in question.options
            ],
            multi_select=question.multi_select,
        ).model_dump()
        for question in request.questions
    ]


def _custom(text: Any) -> str:
    """Typed text, kept to what the harness accepts: printable, newlines allowed."""
    return "".join(char for char in str(text) if char.isprintable() or char == "\n").strip()


def answers_to_response(request: AskUserRequest, answers: list[Any]) -> AskUserResponse:
    """The surface's answers - a list parallel to the questions - as the harness reads them.

    The client is untrusted, so nothing it sends can fail the run: a label the
    question did not offer is dropped, a second pick on a single-select question
    is ignored, and a question left without a usable answer reads "(skipped)".
    Every question skipped is the person declining, which the model is told.
    """
    picked: list[AskUserAnswer] = []
    answered = False
    for index, question in enumerate(request.questions):
        raw = answers[index] if index < len(answers) else None
        entry = raw if isinstance(raw, dict) else {}
        offered = [option.label for option in question.options]
        selected = entry.get("selected")
        labels = [
            label
            for label in dict.fromkeys(selected if isinstance(selected, list) else [])
            if label in offered
        ]
        if not question.multi_select:
            labels = labels[:1]
        typed = "" if entry.get("skipped") else _custom(entry.get("answer", ""))
        if labels:
            picked.append(AskUserAnswer(header=question.header, selected=tuple(labels)))
            answered = True
        elif typed:
            picked.append(AskUserAnswer(header=question.header, custom_answer=typed))
            answered = True
        else:
            picked.append(AskUserAnswer(header=question.header, custom_answer="(skipped)"))
    if not answered:
        return AskUserResponse(cancelled=True)
    return AskUserResponse(answers=tuple(picked))


def asking_delegate() -> str | None:
    """The delegate whose `ask_parent` is running, or `None` for the main agent.

    `ask_parent` hands the surface the question and nothing else, so a stored
    question could say that one was asked and not who asked it - and a specialist
    asking reads differently in a transcript from the agent the person is talking
    to asking (#1042). The library binds the delegation's state for the duration
    of the delegation, so it is bound in the call this is made from and unbound
    again the moment the delegation returns.

    **Call it where the question is put, not where its answer arrives.** The
    answer comes back on the socket's receive loop, which is a different task
    with no delegation bound, and this would answer `None` for every question.
    """
    state = current_subagent_state()
    return state.name if state is not None else None


def render_answer(answer: dict[str, Any] | None) -> str:
    """One collected answer, as the model should read it.

    A missing or malformed entry is "(no answer)" rather than an error: the surface
    returns a list parallel to the questions, and a delegate that asked one question
    reads one answer whether or not the person typed anything.
    """
    if not isinstance(answer, dict):
        return "(no answer)"
    if answer.get("skipped"):
        return "(skipped)"
    selected = answer.get("selected")
    if isinstance(selected, list) and selected:
        return ", ".join(str(label) for label in selected)
    return str(answer.get("answer", "")).strip() or "(no answer)"


def format_answers(questions: list[dict[str, Any]], answers: list[dict[str, Any]]) -> str:
    """Render the collected answers as a readable Q/A transcript for the model."""
    lines: list[str] = []
    for i, q in enumerate(questions):
        a = answers[i] if i < len(answers) else None
        lines.append(f"Q: {q.get('question', '')}\nA: {render_answer(a)}")
    return "\n\n".join(lines)
