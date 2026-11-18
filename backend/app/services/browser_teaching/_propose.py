"""What a reviewed demonstration becomes: one bounded skill proposal (#113, slice 2).

The proposal body is rendered here from three things only: the reviewed steps
(the stored action and role, and the reviewer's own label and parameter name),
the parameter names, and the session's allowed origins. No model reads the
demonstration, so nothing the page showed can reach the proposal, and nothing
outside the allowed origins can be named in it.
"""

import hashlib
import json
from uuid import UUID

from app.core.browser_teaching import CONTROL_ACTIONS, CapturedStep, ReviewedStep, TeachingReason
from app.db.models.browser_teaching import BrowserTeachingSession

PARAMETER_ACTIONS = frozenset({"input_parameter", "select"})


def steps_of(
    row: BrowserTeachingSession,
) -> tuple[tuple[CapturedStep, ...], dict[int, ReviewedStep]]:
    events = tuple(CapturedStep.model_validate(item) for item in row.sanitized_events)
    review = {
        step.sequence: step for step in (ReviewedStep.model_validate(item) for item in row.review)
    }
    return events, review


def review_refusal(
    events: tuple[CapturedStep, ...], review: tuple[ReviewedStep, ...]
) -> TeachingReason | None:
    """Why this review cannot be stored against these steps, or `None` when it can."""
    by_sequence = {event.sequence: event for event in events}
    for step in review:
        event = by_sequence.get(step.sequence)
        if event is None:
            return TeachingReason.REVIEW_UNKNOWN_STEP
        if step.parameter is not None and (
            event.human_step or event.action not in PARAMETER_ACTIONS
        ):
            return TeachingReason.REVIEW_UNKNOWN_STEP
    return None


def proposal_refusal(
    events: tuple[CapturedStep, ...], review: dict[int, ReviewedStep]
) -> TeachingReason | None:
    """Why the review is not finished: every control needs a label, every typed input a parameter."""
    if not events:
        return TeachingReason.REVIEW_INCOMPLETE
    for event in events:
        step = review.get(event.sequence)
        if event.human_step:
            continue
        if event.action in CONTROL_ACTIONS and (step is None or step.label is None):
            return TeachingReason.REVIEW_INCOMPLETE
        if event.action == "input_parameter" and (step is None or step.parameter is None):
            return TeachingReason.REVIEW_INCOMPLETE
    return None


def source_hash(row: BrowserTeachingSession, name: str) -> str:
    """The hash of exactly what a proposal would be built from; the build job is keyed by it."""
    events, review = steps_of(row)
    content = {
        "session": str(row.id),
        "name": name,
        "origins": sorted(row.allowed_origins),
        "steps": [
            [
                event.sequence,
                event.action,
                event.origin,
                None if event.target is None else event.target.role,
                event.direction,
                event.human_step,
                None if event.sequence not in review else review[event.sequence].label,
                None if event.sequence not in review else review[event.sequence].parameter,
            ]
            for event in events
        ],
    }
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _line(event: CapturedStep, step: ReviewedStep | None) -> str:
    label = None if step is None else step.label
    named = f'"{label}"' if label else "the step"
    role = "" if event.target is None else f" ({event.target.role})"
    if event.human_step:
        return f"Stop and ask the person to complete {named} themselves (sign-in or verification) on {event.origin}."
    if event.action == "navigate":
        return f"Go to {named} on {event.origin}." if label else f"Open a page on {event.origin}."
    if event.action == "scroll":
        return f"Scroll {event.direction} to {named}." if label else f"Scroll {event.direction}."
    if event.action == "checkpoint":
        return (
            f"Check that {named} is shown."
            if label
            else "Check that the page shows the expected state."
        )
    parameter = None if step is None else step.parameter
    if event.action == "input_parameter":
        return f"Enter `{{{parameter}}}` in {named}{role}."
    if event.action == "select":
        return (
            f"Choose `{{{parameter}}}` in {named}{role}." if parameter else f"Choose {named}{role}."
        )
    return f"Click {named}{role}."


def render(row: BrowserTeachingSession, name: str) -> tuple[str, str]:
    """The proposal's description and body, from reviewed steps, parameter names and origins only."""
    events, review = steps_of(row)
    origins = sorted(row.allowed_origins)
    parameters = tuple(dict.fromkeys(step.parameter for step in review.values() if step.parameter))
    lines = [
        f"# {name}",
        "",
        "A procedure a person demonstrated in a managed browser and reviewed step by step.",
        "Use it only on these origins:",
        "",
        *(f"- {origin}" for origin in origins),
        "",
    ]
    if parameters:
        lines += ["## Parameters", "", *(f"- `{parameter}`" for parameter in parameters), ""]
    lines += [
        "## Steps",
        "",
        *(
            f"{index}. {_line(event, review.get(event.sequence))}"
            for index, event in enumerate(events, start=1)
        ),
        "",
        "## How to follow it",
        "",
        "Observe each page before acting and match the intended control again. Stop and report",
        "when the page no longer fits a step. Never repeat a submission without the person's request.",
    ]
    description = f"Reviewed browser procedure for {', '.join(origins)}"[:500]
    return description, "\n".join(lines) + "\n"


def job_key(session_id: UUID, digest: str) -> str:
    return f"browser-teaching:{session_id}:{digest}"
