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

import anyio

from app.agents.browser_events import (
    BrowseOutcome,
    BrowserCommand,
    BrowserControl,
    BrowserEvent,
    BrowserEventSink,
)
from app.agents.browser_sign_ins import SignIn
from app.agents.capabilities.browser_use._decision import (
    AskPerson,
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


HOLD_LIMIT = 900.0
"""How long, in seconds, a person may hold the browser before it is handed back.

Long enough to sign in with a second factor and find the right page; bounded,
because a person who walked away would otherwise hold the run open for as long as
it may live.
"""

WAIT_FOR_PERSON = 600.0
"""How long, in seconds, a browse that asked for a person waits for one to take over."""

FRAME_EVERY = 1.0
"""Seconds between pictures while a person holds the browser and is not acting."""

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

    async def click_at(self, x: float, y: float) -> None:
        """Press at viewport coordinates - a person's click while they hold the tab."""

    async def insert_text(self, text: str) -> None:
        """Type into whatever has focus, as a person holding the tab does."""

    async def press(self, key: str) -> None:
        """Press one key that has no character - Enter, Tab, an arrow."""

    async def wheel(self, dy: float) -> None:
        """Scroll by `dy` pixels where the page is, as a mouse wheel does."""

    async def capture_sign_in(self) -> SignIn | None:
        """The sign-in to the site this tab is on, or `None` on a page off the web."""


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

RememberSignIn = Callable[["PageSession", BrowserCommand], Awaitable[str | None]]
"""Keep the sign-in on the page a person hands back, answering with its site (#2129).

`None` when nothing was kept - the give-back came from someone other than the
person the run acts for, or the tab is not on a site.
"""


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
    control: BrowserControl | None = None,
    run_id: str | None = None,
    remember: RememberSignIn | None = None,
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
        control: Where the people watching ask to take the browser over, or `None`
            where nobody can - then an `ask_person` step ends the browse blocked.
        run_id: The run, carried on the opening frame so a surface can link to
            the browse's live view.
        remember: Keeps a sign-in a person asks to keep when they hand the
            browser back, or `None` where this run may not keep one.

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
            run_id=run_id,
        )
    )

    recent: list[str] = []
    for taken in range(1, policy.max_steps + 1):
        session.steps += 1
        step_no = session.steps
        held = False
        if control is not None:
            # Between steps, never inside one: a person taking over waits for the
            # action in flight to finish, so the tab is never driven by two at once.
            waiting = await control.poll()
            if waiting is not None and waiting.type == "take_over":
                await _held(
                    session, control, emit, call_id=call_id, by=waiting.by, remember=remember
                )
                held = True
        if taken > 1 or held:
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
        if isinstance(action, AskPerson):
            arrived = None
            if control is not None:
                await emit(
                    BrowserEvent(
                        kind="browser_needs_person",
                        call_id=call_id,
                        step=step_no,
                        url=snapshot.url,
                        title=snapshot.title,
                        detail=action.reason,
                    )
                )
                arrived = await _await_person(control)
            if arrived is None or control is None:
                reason = f"It needed a person and nobody took the browser over: {action.reason}"
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
            session.history += (f"step {step_no}: {step.next_goal} - asked a person",)
            await _held(session, control, emit, call_id=call_id, by=arrived.by, remember=remember)
            continue
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
    AskPerson: "ASK_PERSON",
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


async def _await_person(control: BrowserControl) -> BrowserCommand | None:
    """The `take_over` that answers an `ask_person`, or `None` once nobody came.

    Anything else that arrives meanwhile is input for a browser nobody holds yet,
    and is dropped rather than queued for later.
    """
    with anyio.move_on_after(WAIT_FOR_PERSON):
        while True:
            command = await control.wait(FRAME_EVERY)
            if command is not None and command.type == "take_over":
                return command
    return None


async def _held(
    session: BrowseSession,
    control: BrowserControl,
    emit: Callable[[BrowserEvent], Awaitable[bool]],
    *,
    call_id: str,
    by: str | None,
    remember: RememberSignIn | None,
) -> None:
    """Hand the tab to a person until they give it back, or until `HOLD_LIMIT`.

    The person's input reaches the page as it arrives, and a picture follows each
    one - and one a second while they are reading - so the view they act on is
    the page as it is. What they type is never recorded: the history says only
    that somebody took over, which is also what the model is told to look again
    because of. A give-back that asks to keep the sign-in keeps it before the
    agent touches the page again, and the release says which site it kept.
    """
    page = session.page
    await emit(BrowserEvent(kind="browser_held", call_id=call_id, step=session.steps, by=by))
    kept: str | None = None
    with anyio.move_on_after(HOLD_LIMIT):
        while True:
            command = await control.wait(FRAME_EVERY)
            if command is not None and command.type == "give_back":
                if command.remember and remember is not None:
                    kept = await remember(page, command)
                break
            if command is not None:
                await _person_input(page, command)
            image = await page.screenshot()
            if image is not None:
                await emit(
                    BrowserEvent(
                        kind="browser_frame", call_id=call_id, step=session.steps, image=image
                    )
                )
    await emit(
        BrowserEvent(kind="browser_released", call_id=call_id, step=session.steps, detail=kept)
    )
    session.history += (
        f"step {session.steps}: a person took the browser over and handed it back - "
        f"look at the page again before acting",
    )


async def _person_input(page: PageSession, command: BrowserCommand) -> None:
    """Carry out one thing a person did in the tab they hold; drop one that says nothing."""
    if command.type == "click" and command.x is not None and command.y is not None:
        await page.click_at(command.x, command.y)
    elif command.type == "type" and command.text:
        await page.insert_text(command.text)
    elif command.type == "key" and command.key is not None:
        await page.press(command.key)
    elif command.type == "scroll" and command.dy is not None:
        await page.wheel(command.dy)


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
