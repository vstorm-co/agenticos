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

import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, nullcontext
from dataclasses import dataclass, field, replace
from hashlib import sha256
from typing import Protocol

import anyio
import logfire

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
from app.agents.capabilities.browser_use._plans import PlanStep, record, replay

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

FIRST_FIT_WAIT = 1.0
"""How long, in seconds, the first step waits for a watching window to say its size.

The window connects when the browse opens and sends its size about 60 ms later
(measured on the chat's split view); the first step used to start before that, so
it - and a whole one-step browse - ran at the default width and was shown shrunk
into a narrower panel. Bounded, because a browse nobody watches has nobody to wait for.
"""

_FIT_POLL = 0.05
"""How often, in seconds, the first step looks for the window's size while it waits."""

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

    plan: tuple[PlanStep, ...] = ()
    """The steps that got a `done` browse there, to replay next time - see `_plans`."""

    replayed: int = 0
    """How many of this browse's steps were replayed rather than asked of the model."""


class PageSession(Protocol):
    """A live page, reduced to what the loop does to one.

    The seam between this loop and CDP. `_page.py` implements it against a real
    browser; a test implements it against a list of snapshots, which is why none
    of the reasoning above needs Chromium to verify.
    """

    async def snapshot(self) -> Snapshot:
        """The page as it is now: its URL, its title, its words and what can be chosen."""

    def stream(
        self, deliver: Callable[[str], Awaitable[None]]
    ) -> AbstractAsyncContextManager[None]:
        """Hand the page's paints to `deliver` as JPEG `data:` URLs while the block runs."""

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

    async def resize(self, width: int, height: int, scale: int) -> None:
        """Lay the page out for a window `width` by `height`, drawn at `scale`."""

    async def point(self, element: Element) -> tuple[float, float] | None:
        """Where `element` is now, as fractions of the viewport, or `None` off it."""

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
    last: Snapshot | None = None
    """The page as the agent last read it, whose element numbers a direct action names."""

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


@dataclass
class _Plan:
    """A browse's replay and its recording, kept beside the loop that does both."""

    pending: list[PlanStep]
    recorded: list[PlanStep] = field(default_factory=list)
    recording: bool = True
    replayed: int = 0


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
    plan: Sequence[PlanStep] = (),
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
        plan: Steps an earlier browse of this task took, replayed without the
            model while the page still fits them - see `_plans`.

    Returns:
        The outcome, the answer, the page and how many steps this call took. Never
        raises for a page's behaviour - a page that cannot be worked with is
        `blocked`, which is an answer.
    """
    kept = _Plan(pending=list(plan))
    result = await _drive(
        task=task,
        session=session,
        decide=decide,
        policy=policy,
        call_id=call_id,
        sink=sink,
        control=control,
        run_id=run_id,
        remember=remember,
        kept=kept,
    )
    return replace(
        result,
        plan=tuple(kept.recorded) if result.outcome == "done" else (),
        replayed=kept.replayed,
    )


async def _drive(
    *,
    task: str,
    session: BrowseSession,
    decide: Decide,
    policy: LoopPolicy,
    call_id: str,
    sink: BrowserEventSink | None,
    control: BrowserControl | None,
    run_id: str | None,
    remember: RememberSignIn | None,
    kept: _Plan,
) -> BrowseResult:
    """`run_browse`'s loop, replaying and recording into `kept` as it goes."""
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

    async def push(image: str) -> None:
        """One painted frame of the page, to whoever is still watching."""
        nonlocal previews_land
        if previews_land:
            previews_land = await emit(
                BrowserEvent(kind="browser_frame", call_id=call_id, step=session.steps, image=image)
            )

    # The page as it paints, for as long as somebody watches - a scroll or a page
    # loading shows as it happens, not as a slide when the next step is taken.
    # The step's own picture below still carries the address and the title.
    async with page.stream(push) if previews_land else nullcontext():
        recent: list[str] = []
        for taken in range(1, policy.max_steps + 1):
            session.steps += 1
            step_no = session.steps
            was_held = False
            resized = False
            if control is not None:
                # Between steps, never inside one: a person taking over waits for the
                # action in flight to finish, so the tab is never driven by two at once.
                waiting, resized = (
                    await first_fit(page, control)
                    if taken == 1 and previews_land
                    else await between_steps(page, control)
                )
                if waiting is not None:
                    await held(
                        session,
                        control,
                        emit,
                        call_id=call_id,
                        by=waiting.by,
                        by_user_id=waiting.by_user_id,
                        remember=remember,
                    )
                    was_held = True
            # A resized page has laid itself out again, so the first step's snapshot
            # - taken before the loop - would offer elements where they no longer are.
            clock = _StepClock()
            if taken > 1 or was_held or resized:
                snapshot = await page.snapshot()
            # What a direct action after this browse would name by number.
            session.last = snapshot
            clock.mark("snapshot")

            image: str | None = None
            if previews_land or policy.vision:
                image = await page.screenshot()
            clock.mark("screenshot")
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

            # A step this person's earlier browse of the same task took, while the
            # page still offers it - no model call. The first step that does not
            # fit ends the replay for good: the page has moved on from the recording.
            again = replay(kept.pending[0], snapshot) if kept.pending else None
            if again is not None:
                kept.pending.pop(0)
                kept.replayed += 1
                step = Step(
                    evaluation="Replayed from an earlier browse of this task.",
                    memory=session.memory,
                    next_goal="Repeat a step that worked the last time this task was done.",
                    action=again,
                )
            else:
                kept.pending.clear()
                step = await decide(
                    task,
                    snapshot,
                    session.history,
                    session.memory,
                    image if policy.vision else None,
                )
            clock.mark("decide")
            session.memory = step.memory
            action = step.action
            element = element_at(
                snapshot, action.index if isinstance(action, (Click, TypeText, Select)) else None
            )
            await emit(
                BrowserEvent(
                    kind="browser_step",
                    call_id=call_id,
                    step=step_no,
                    url=snapshot.url,
                    title=snapshot.title,
                    operation=OPERATION[type(action)],
                    target=target_of(action, element),
                    reason=step.next_goal,
                )
            )
            if previews_land and element is not None:
                # Where the agent is about to press, for the cursor a person watches
                # move across the page - only while somebody is watching, and before
                # the action, so the cursor arrives as the click happens.
                spot = await page.point(element)
                if spot is not None:
                    await emit(
                        BrowserEvent(
                            kind="browser_pointer",
                            call_id=call_id,
                            step=step_no,
                            x=spot[0],
                            y=spot[1],
                        )
                    )

            if isinstance(action, Done):
                clock.log(step_no, OPERATION[type(action)])
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
                await held(
                    session,
                    control,
                    emit,
                    call_id=call_id,
                    by=arrived.by,
                    by_user_id=arrived.by_user_id,
                    remember=remember,
                )
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
                result = await act(page, step, element)
            except StaleElement as refused:
                # The page moved between the snapshot and the decision, or the number
                # named nothing. The action did not happen and the next snapshot
                # describes what is there now - one wasted step with a reason the
                # model reads, not the end of the browse. The repeat guard is what
                # stops a page that does this for ever.
                result = f"refused: {refused}"
            else:
                # Typing ends the recording: what was typed is the person's, and a
                # replay that stopped short of it leaves the model to type it again.
                if isinstance(action, TypeText):
                    kept.recording = False
                elif kept.recording and (taken_step := record(snapshot, action, element)):
                    kept.recorded.append(taken_step)
            clock.mark("act")
            session.history += (f"step {step_no}: {step.next_goal} - {result}",)
            await page.settle()
            clock.mark("settle")
            clock.log(step_no, OPERATION[type(action)])

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


OPERATION: dict[type, str] = {
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


def target_of(action: object, element: Element | None) -> str | None:
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


class _StepClock:
    """How long each part of one step took, logged once the step is done.

    A browse that feels slow is slow somewhere specific - reading the page, the
    model deciding, the action, or waiting for the page to settle - and which one
    decides what to fix. One trace entry per step, in milliseconds, so a run's
    trace reads as a profile of the browse.
    """

    def __init__(self) -> None:
        self._last = time.perf_counter()
        self._parts: dict[str, int] = {}

    def mark(self, part: str) -> None:
        now = time.perf_counter()
        self._parts[part] = round((now - self._last) * 1000)
        self._last = now

    def log(self, step: int, operation: str) -> None:
        # Into the trace beside the run's own spans, where the rest of a run's
        # timing is read - the application's stdlib loggers stop at WARNING.
        parts = self._parts
        logfire.info(
            "browse step {step} ({operation}): snapshot {snapshot_ms}ms, screenshot "
            "{screenshot_ms}ms, decide {decide_ms}ms, act {act_ms}ms, settle {settle_ms}ms",
            step=step,
            operation=operation,
            snapshot_ms=parts.get("snapshot"),
            screenshot_ms=parts.get("screenshot"),
            decide_ms=parts.get("decide"),
            act_ms=parts.get("act"),
            settle_ms=parts.get("settle"),
        )


def element_at(snapshot: Snapshot, index: int | None) -> Element | None:
    """The element a step named, or `None` when it named none or a number not on the page."""
    if index is None:
        return None
    for element in snapshot.elements:
        if element.index == index:
            return element
    return None


async def act(page: PageSession, step: Step, element: Element | None) -> str:
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


async def held(
    session: BrowseSession,
    control: BrowserControl,
    emit: Callable[[BrowserEvent], Awaitable[bool]],
    *,
    call_id: str,
    by: str | None,
    by_user_id: str | None,
    remember: RememberSignIn | None,
) -> None:
    """Hand the tab to a person until they give it back, or until `HOLD_LIMIT`.

    Only that person's input and give-back are acted on: everyone else who may
    drive the browse still sends commands down the same queue, and a click from
    a second viewer must not land on a page somebody else is holding.

    The person's input reaches the page as it arrives, and a picture follows each
    one - and one a second while they are reading - so the view they act on is
    the page as it is. What they type is never recorded: the history says only
    that somebody took over, which is also what the model is told to look again
    because of. A give-back that asks to keep the sign-in keeps it before the
    agent touches the page again, and the release says which site it kept.
    """
    page = session.page
    await emit(
        BrowserEvent(
            kind="browser_held", call_id=call_id, step=session.steps, by=by, by_user_id=by_user_id
        )
    )
    kept: str | None = None
    with anyio.move_on_after(HOLD_LIMIT):
        while True:
            command = await control.wait(FRAME_EVERY)
            if command is not None and by_user_id is not None and command.by_user_id != by_user_id:
                command = None
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


async def hand_over(
    session: BrowseSession,
    control: BrowserControl,
    emit: Callable[[BrowserEvent], Awaitable[bool]],
    *,
    call_id: str,
    by: str,
    by_user_id: str,
    remember: RememberSignIn,
) -> None:
    """Give a person a tab with no agent in it, until they hand it back.

    Signing in to a site from Settings (#2129): the same hold a take-over is, from
    the first frame, and the same give-back that keeps the sign-in.
    """
    await held(
        session, control, emit, call_id=call_id, by=by, by_user_id=by_user_id, remember=remember
    )


async def between_steps(
    page: PageSession, control: BrowserControl
) -> tuple[BrowserCommand | None, bool]:
    """What arrived while the last step ran: the take-over, if any, and whether the page was resized.

    Every waiting command is read, not one a step: a window resized a few times
    while the model was thinking queues a resize for each, and handing them out
    one per step would leave the page a size behind the window for as many steps.
    Input for a tab nobody holds - a click before the take-over landed - is dropped.
    """
    resized = False
    while (command := await control.poll()) is not None:
        if command.type == "take_over":
            return command, resized
        if command.type == "resize":
            await _person_input(page, command)
            resized = True
    return None, resized


async def first_fit(
    page: PageSession, control: BrowserControl
) -> tuple[BrowserCommand | None, bool]:
    """`between_steps` for the first step, which waits briefly for the window's size.

    Up to `FIRST_FIT_WAIT`, and only until something arrives: a size is applied
    and the step starts at once, and a take-over is handed back as it would be
    between any two steps.
    """
    deadline = time.monotonic() + FIRST_FIT_WAIT
    while True:
        waiting, resized = await between_steps(page, control)
        if waiting is not None or resized or time.monotonic() >= deadline:
            return waiting, resized
        await anyio.sleep(_FIT_POLL)


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
    elif command.type == "resize" and command.width is not None and command.height is not None:
        await page.resize(command.width, command.height, command.scale or 1)


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
