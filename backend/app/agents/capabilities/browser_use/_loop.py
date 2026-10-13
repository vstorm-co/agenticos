"""The browse loop: snapshot, decide, act, repeat - and stop for a reason.

Every dependency is injected, so the loop is exercised end to end without a
browser and without a language model. What is left here is the part worth
reading: what each action does, how a long task carries on across calls, and the
four ways a browse ends.

**Four outcomes and no fifth.** `done` reached the goal. `blocked` is the model
saying the page offers nothing that serves it. `exhausted` hit this call's step
ceiling. `failed` is the browser or the endpoint. The distinction is the
capability's point: a loop that can only succeed or time out reports a sign-in
wall and a crashed browser identically, and a person reading the transcript
cannot tell which one they need to fix.

**A ceiling is a pause, not an end.** The tab, the history and the model's memory
live in a :class:`BrowseSession` that outlives one call, so a task that runs out of
steps is picked up by the next call where it stopped instead of starting over from
the first page (#2127).

**A guard, because a bounded action space is not a bounded run.** A page can offer
a perfectly legitimate action for ever - the cookie banner that reappears, the
"load more" that loads nothing - and choosing it each time is the model behaving
plausibly all the way to its ceiling. So the identical action on the identical
page, three times running, ends the browse as `blocked` while there is still
something useful to say.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from app.agents.browser_events import BrowseOutcome, BrowserEvent, BrowserEventSink
from app.agents.capabilities.browser_use._decision import (
    Blocked,
    Click,
    Done,
    GoBack,
    Navigate,
    Scroll,
    Select,
    Step,
    TypeText,
    Wait,
    describe,
)
from app.agents.capabilities.browser_use._elements import Element, Snapshot
from app.agents.capabilities.browser_use._page import StaleElement

REPEAT_LIMIT = 3
"""How often the identical action on the identical page is tried before giving up.

Two is too few - a page that genuinely needs the same button pressed twice exists -
and the cost of a third is one step. Beyond that it is a loop, not a retry.
"""


_DETAIL_LIMIT = 600
"""How much of a finished browse's answer the finish frame carries to the panel."""


@dataclass(frozen=True, slots=True)
class BrowseResult:
    """How a browse ended, and what it has to say about it."""

    outcome: BrowseOutcome
    text: str
    """The model's answer on `done`; otherwise what it remembered and why it stopped."""

    page: str
    """The page's text where the browse ended, for the caller to read for itself."""

    steps: int
    """Steps this call took."""


class PageSession(Protocol):
    """A live page, reduced to what the loop does to one.

    The seam between this loop and CDP. `_page.py` implements it against a real
    browser; a test implements it against a list of snapshots, which is why none
    of the reasoning above needs Chromium to verify.
    """

    async def snapshot(self) -> Snapshot:
        """The page as it is now: its URL, its title, its words and what can be chosen."""

    async def click(self, element: Element) -> None:
        """Press an element, resolved and verified where it is now."""

    async def type_text(self, element: Element, text: str) -> None:
        """Focus a field and enter `text`, replacing whatever it held."""

    async def select(self, element: Element, value: str) -> None:
        """Choose `value` in a native dropdown, firing what a person's choice fires."""

    async def scroll(self, direction: str) -> None:
        """Move one viewport `down` or `up`."""

    async def navigate(self, url: str) -> None:
        """Open `url` in this tab, refused outside the agent's allowed domains."""

    async def back(self) -> None:
        """Return to the previous page in this tab's history."""

    async def settle(self, *, leaving: str | None = None) -> None:
        """Wait for whatever the last action started, and for the page to be ready."""

    async def screenshot(self) -> str | None:
        """The viewport as a `data:` URL."""

    async def read(self) -> str:
        """The page's readable text, which is what a finished browse answers with."""


@dataclass
class BrowseSession:
    """One tab and what the model has learned in it, carried from call to call.

    Opened by the first `browse_web` call of a run and closed when the run ends,
    so a second call continues on the page the first one left - signed in, half
    way through a form - with the memory the model kept, instead of a stranger
    starting again from a URL.
    """

    page: PageSession
    history: tuple[str, ...] = ()
    memory: str = ""
    steps: int = 0
    """Steps taken in this tab across every call, which is what the frames number."""

    def restart(self) -> None:
        """Forget the task, keep the tab - for a call that starts a new one in it."""
        self.history = ()
        self.memory = ""


Decide = Callable[[str, Snapshot, tuple[str, ...], str, str | None], Awaitable[Step]]
"""Ask the browsing model for one step: task, page, history, memory, screenshot."""


@dataclass(frozen=True, slots=True)
class LoopPolicy:
    """What an operator decided about how far and what to send, as one object.

    Passed rather than read from a module constant so the whole policy is visible
    at the call site and settable per agent - an agent that browses a slow internal
    tool and one that reads public docs want different numbers.
    """

    max_steps: int
    preview: bool
    """Send each step's viewport to the chat while the browse runs."""

    vision: bool = False
    """Send each step's viewport to the browsing model as well as its table."""


async def run_browse(
    *,
    task: str,
    session: BrowseSession,
    decide: Decide,
    policy: LoopPolicy,
    call_id: str,
    sink: BrowserEventSink | None = None,
) -> BrowseResult:
    """Drive `session.page` towards `task`, narrating as it goes, and stop for a reason.

    Args:
        task: The self-contained task the calling model handed over.
        session: The tab, and what earlier calls in this run did in it.
        decide: One request to the browsing model per step.
        policy: The ceiling and what to send to whom.
        call_id: Which `browse_web` call this is, so a surface can keep two
            browses in one turn apart.
        sink: Where the frames go, or `None` on a surface that cannot show them.

    Returns:
        The outcome, the answer, the page and how many steps this call took. Never
        raises for a page's behaviour - a page that cannot be worked with is
        `blocked`, which is an answer.
    """
    # Whether anybody is still watching. A run whose reader closed the tab carries
    # on by design, and encoding a JPEG per step for a closed socket would be the
    # most expensive thing in the loop done for nobody.
    previews_land = policy.preview

    async def emit(event: BrowserEvent) -> bool:
        """Send one frame, and answer whether a surface received it."""
        if sink is None:
            return True
        return await sink(event)

    page = session.page
    snapshot = await page.snapshot()
    await emit(
        BrowserEvent(
            kind="browser_opened",
            call_id=call_id,
            step=session.steps,
            url=snapshot.url,
            title=snapshot.title,
            goal=task,
            max_steps=session.steps + policy.max_steps,
        )
    )

    recent: list[str] = []
    for taken in range(1, policy.max_steps + 1):
        session.steps += 1
        step_no = session.steps
        if taken > 1:
            snapshot = await page.snapshot()

        image: str | None = None
        if previews_land or policy.vision:
            image = await page.screenshot()
        if previews_land and image is not None:
            previews_land = await emit(
                BrowserEvent(
                    kind="browser_frame",
                    call_id=call_id,
                    step=step_no,
                    url=snapshot.url,
                    title=snapshot.title,
                    image=image,
                )
            )

        step = await decide(
            task, snapshot, session.history, session.memory, image if policy.vision else None
        )
        session.memory = step.memory
        action = step.action
        element = _element_at(
            snapshot, action.index if isinstance(action, (Click, TypeText, Select)) else None
        )
        await emit(
            BrowserEvent(
                kind="browser_step",
                call_id=call_id,
                step=step_no,
                url=snapshot.url,
                title=snapshot.title,
                operation=_OPERATION[type(action)],
                target=_target(action, element),
                reason=step.next_goal,
            )
        )

        if isinstance(action, Done):
            return await _finish(
                emit,
                session,
                call_id=call_id,
                outcome="done",
                taken=taken,
                text=action.answer,
                # The answer itself, so the panel says what was found rather than
                # that something was. Model-written; a surface renders it as data.
                detail=action.answer[:_DETAIL_LIMIT],
                snapshot=snapshot,
            )
        if isinstance(action, Blocked):
            return await _finish(
                emit,
                session,
                call_id=call_id,
                outcome="blocked",
                taken=taken,
                text=_remembered(session, action.reason),
                detail=action.reason,
                snapshot=snapshot,
            )

        signature = _signature(snapshot, step)
        recent.append(signature)
        if recent[-REPEAT_LIMIT:].count(signature) == REPEAT_LIMIT:
            reason = (
                f"The same action was chosen {REPEAT_LIMIT} times running without "
                f"changing the page."
            )
            return await _finish(
                emit,
                session,
                call_id=call_id,
                outcome="blocked",
                taken=taken,
                text=_remembered(session, reason),
                detail=reason,
                snapshot=snapshot,
            )

        try:
            result = await _act(page, step, element)
        except StaleElement as refused:
            # The page moved between the snapshot and the decision, or the number
            # named nothing. The action did not happen and the next snapshot
            # describes what is there now - one wasted step with a reason the
            # model reads, not the end of the browse. The repeat guard is what
            # stops a page that does this for ever.
            result = f"refused: {refused}"
        session.history += (f"step {step_no}: {step.next_goal} - {result}",)
        await page.settle()

    reason = (
        f"Stopped after {policy.max_steps} steps without finishing. Call again without "
        f"a start_url to continue in the same tab."
    )
    return await _finish(
        emit,
        session,
        call_id=call_id,
        outcome="exhausted",
        taken=policy.max_steps,
        text=_remembered(session, reason),
        detail=reason,
        snapshot=snapshot,
    )


_OPERATION: dict[type, str] = {
    Click: "CLICK",
    TypeText: "TYPE_TEXT",
    Select: "SELECT",
    Scroll: "SCROLL",
    Navigate: "NAVIGATE",
    GoBack: "BACK",
    Wait: "WAIT",
    Done: "DONE",
    Blocked: "BLOCKED",
}
"""Each action as the frame names it - the vocabulary a surface already draws."""


def _target(action: object, element: Element | None) -> str | None:
    """What a frame says the action applied to: the element's label, or the address."""
    if isinstance(action, Navigate):
        return action.url
    return element.label if element is not None else None


def _remembered(session: BrowseSession, reason: str) -> str:
    """What a browse that did not finish has to say: why, and what it had learned."""
    if not session.memory:
        return reason
    return f"{reason}\n\nWhat it had learned: {session.memory}"


def _signature(snapshot: Snapshot, step: Step) -> str:
    """What makes one step distinguishable from the step before it.

    The scroll position, because scrolling down a long page is the same URL and the
    same action three times running, and it is progress. What the page offers,
    because a URL is not a state: a wizard, a paginated table and a filter that
    rewrites its results in place all present `Next` at the same index on the same
    address, and each click advanced the flow.

    Roles and labels, and deliberately not values or the page's text: a field's
    value changes the moment it is typed into, and the text of any page with a
    clock or a carousel differs every step, so either would make a real loop look
    like progress. A page whose *labels* churn is not caught here, and `max_steps`
    is what stops it.
    """
    offered = "␟".join(f"{element.role}:{element.label}" for element in snapshot.elements)
    state = f"{snapshot.url}|{snapshot.scroll_y}|{offered}"
    return f"{sha256(state.encode()).hexdigest()}|{step.action.model_dump_json()}"


def _element_at(snapshot: Snapshot, index: int | None) -> Element | None:
    """The element a step named, or `None` when it named none or a number not on the page."""
    if index is None:
        return None
    for element in snapshot.elements:
        if element.index == index:
            return element
    return None


async def _act(page: PageSession, step: Step, element: Element | None) -> str:
    """Carry out one step's action.

    Returns:
        The history line describing what was done, which the next step reads.

    Raises:
        StaleElement: The action names an element this page does not offer, or
            the page layer refused it where it is now.
    """
    action = step.action
    if isinstance(action, Scroll):
        await page.scroll(action.direction)
    elif isinstance(action, Navigate):
        await page.navigate(action.url)
    elif isinstance(action, GoBack):
        await page.back()
    elif isinstance(action, (Click, TypeText, Select)):
        if element is None:
            raise StaleElement(f"There is no element {action.index} on this page.")
        if isinstance(action, Click):
            await page.click(element)
        elif isinstance(action, TypeText):
            await page.type_text(element, action.text)
        else:
            await page.select(element, action.option)
    return describe(step)


async def _finish(
    emit: Callable[[BrowserEvent], Awaitable[bool]],
    session: BrowseSession,
    *,
    call_id: str,
    outcome: BrowseOutcome,
    taken: int,
    text: str,
    detail: str,
    snapshot: Snapshot,
) -> BrowseResult:
    """Send the closing frame and return the result, for every way a browse ends.

    One function so no exit can forget the frame. A surface that never hears a
    finish leaves a spinner running for ever, and the outcome a reader most needs
    is the one on the paths that are easiest to return from early.
    """
    await emit(
        BrowserEvent(
            kind="browser_finished",
            call_id=call_id,
            step=session.steps,
            url=snapshot.url,
            title=snapshot.title,
            outcome=outcome,
            detail=detail,
        )
    )
    return BrowseResult(outcome=outcome, text=text, page=await session.page.read(), steps=taken)
