"""The steps a finished browse took, kept to take again without asking the model.

Stagehand's action cache, reduced to what is safe here: a browse that finished
records the actions that got it there, and the same person asking the same task
from the same page later replays them - each step only while the page still
offers what the recording says it pressed, and the model takes over at the
first difference.

What is recorded is what the person could see on the page - the address, an
element's role and label, a dropdown option - never what was typed. A browse
that types stops recording at that step, so a password or a search with a name
in it is never kept, and the model types it again.
"""

from hashlib import sha256
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel

from app.agents.capabilities.browser_use._decision import (
    Action,
    Click,
    GoBack,
    Navigate,
    Scroll,
    Select,
)
from app.agents.capabilities.browser_use._elements import Element, Snapshot


class PlanStep(BaseModel):
    """One action a finished browse took, described by what was on the page."""

    op: Literal["click", "select", "scroll", "navigate", "back"]
    at: str
    """Where it was taken: the host and path, without the query a session adds."""

    role: str | None = None
    label: str | None = None
    """The element pressed, as the accessibility tree named it - never its number,
    which is only stable inside one snapshot."""

    option: str | None = None
    direction: Literal["down", "up"] | None = None
    url: str | None = None


def page_of(url: str) -> str:
    """The host and path of `url` - what a later visit to the same page shares."""
    parts = urlsplit(url)
    return f"{parts.netloc}{parts.path}".rstrip("/")


def plan_key(task: str, start_url: str) -> str:
    """Which recording a browse may replay: the same task, from the same page.

    Whitespace and case do not make a different task; anything else does, so a
    plan is only ever taken for the request it was recorded for.
    """
    words = " ".join(task.lower().split())
    return sha256(f"{page_of(start_url)}\n{words}".encode()).hexdigest()


def record(snapshot: Snapshot, action: Action, element: Element | None) -> PlanStep | None:
    """The step to keep for `action`, or `None` for one that is not kept.

    Typing, waiting and every ending are not: typing because what was typed is
    the person's, the rest because they carry no movement to repeat.
    """
    at = page_of(snapshot.url)
    if isinstance(action, Click) and element is not None:
        return PlanStep(op="click", at=at, role=element.role, label=element.label)
    if isinstance(action, Select) and element is not None:
        return PlanStep(
            op="select", at=at, role=element.role, label=element.label, option=action.option
        )
    if isinstance(action, Scroll):
        return PlanStep(op="scroll", at=at, direction=action.direction)
    if isinstance(action, Navigate):
        return PlanStep(op="navigate", at=at, url=action.url)
    if isinstance(action, GoBack):
        return PlanStep(op="back", at=at)
    return None


def replay(step: PlanStep, snapshot: Snapshot) -> Action | None:
    """`step` as an action on this page, or `None` where the page no longer fits it.

    The page has to be the one recorded, and an element to press has to be there
    exactly once under the same role and label - two candidates is a page that
    changed, and guessing between them is how a replay presses the wrong thing.
    """
    if page_of(snapshot.url) != step.at:
        return None
    if step.op == "scroll":
        return Scroll(action="scroll", direction=step.direction or "down")
    if step.op == "back":
        return GoBack(action="back")
    if step.op == "navigate":
        return Navigate(action="navigate", url=step.url) if step.url else None
    matches = [
        element
        for element in snapshot.elements
        if element.role == step.role and element.label == step.label
    ]
    if len(matches) != 1:
        return None
    if step.op == "click":
        return Click(action="click", index=matches[0].index)
    if step.option is None or step.option not in matches[0].options:
        return None
    return Select(action="select", index=matches[0].index, option=step.option)
