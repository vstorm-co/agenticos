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

MAX_QUESTIONS = 10


class QuestionItem(BaseModel):
    """One question to put to the user."""

    question: str = Field(description="The question text.")
    options: list[str] = Field(
        default_factory=list,
        description="Optional suggested answers, shown as numbered choices.",
    )
    allow_custom: bool = Field(
        default=True,
        description="Whether the user may type a free-form answer instead of picking an option.",
    )


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
    return str(answer.get("answer", "")).strip() or "(no answer)"


def format_answers(questions: list[dict[str, Any]], answers: list[dict[str, Any]]) -> str:
    """Render the collected answers as a readable Q/A transcript for the model."""
    lines: list[str] = []
    for i, q in enumerate(questions):
        a = answers[i] if i < len(answers) else None
        lines.append(f"Q: {q.get('question', '')}\nA: {render_answer(a)}")
    return "\n\n".join(lines)
