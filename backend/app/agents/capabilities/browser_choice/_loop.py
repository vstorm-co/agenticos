"""The choose-loop: snapshot, decide, act, repeat - and stop for a reason.

Every dependency is injected, so the loop is exercised end to end without a
browser, without TypeSafe and without a language model. What is left here is the
part worth reading: what each operation does, and the four ways a browse ends.

**Four outcomes and no fifth.** `done` reached the goal. `blocked` is the engine
saying the page offers nothing that serves it. `exhausted` hit the ceiling.
`failed` is the browser or the endpoint. The distinction is the capability's
point: a loop that can only succeed or time out reports a sign-in wall and a
crashed browser identically, and a person reading the transcript cannot tell
which one they need to fix.

**Two guards, because a bounded action space is not a bounded run.** A page can
offer a perfectly legitimate action for ever - the cookie banner that reappears,
the "load more" that loads nothing - and choosing it each time is the loop
behaving correctly all the way to its ceiling. So a repeat of the same action on
the same page ends the browse as `blocked` while there is still something useful
to say, and `min_confidence` lets an operator refuse to act on a pick the decision
model was not sure about.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from app.agents.browser_events import BrowseOutcome, BrowserEvent, BrowserEventSink
from app.agents.capabilities.browser_choice._elements import Element, Snapshot
from app.agents.capabilities.browser_choice._page import StaleElement

REPEAT_LIMIT = 3
"""How often the identical action on the identical page is tried before giving up.

Two is too few - a page that genuinely needs the same button pressed twice exists -
and the cost of a third is one step. Beyond that it is a loop, not a retry.
"""


@dataclass(frozen=True, slots=True)
class Choice:
    """One step's decision, as the loop consumes it."""

    operation: str
    index: int | None
    confidence: float | None


@dataclass(frozen=True, slots=True)
class BrowseResult:
    """How a browse ended, and what it has to say about it."""

    outcome: BrowseOutcome
    text: str
    steps: int


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

    async def scroll(self) -> None:
        """Move one viewport down."""

    async def settle(self) -> None:
        """Wait for whatever the last action started, and for the page to be ready."""

    async def screenshot(self) -> str | None:
        """The viewport as a `data:` URL, or `None` where previews are off."""

    async def read(self) -> str:
        """The page's readable text, which is what a finished browse answers with."""


Decide = Callable[[str, Snapshot, tuple[str, ...]], Awaitable[Choice]]
"""Ask the decision model which operation and which element."""

Generate = Callable[[str, Element, tuple[str, ...]], Awaitable[str]]
"""Ask a language model what to type. The one generated thing in the loop."""


@dataclass(frozen=True, slots=True)
class LoopPolicy:
    """What an operator decided about how far and how sure, as one object.

    Passed rather than read from a module constant so the whole policy is visible
    at the call site and settable per agent - #1829's fourth point, that the loop's
    limits are configuration and not constants somebody edits the source to change.
    """

    max_steps: int
    min_confidence: float
    preview: bool


async def run_browse(
    *,
    goal: str,
    page: PageSession,
    decide: Decide,
    generate: Generate,
    policy: LoopPolicy,
    call_id: str,
    sink: BrowserEventSink | None = None,
) -> BrowseResult:
    """Drive `page` towards `goal`, narrating as it goes, and stop for a reason.

    Args:
        goal: The self-contained task the calling model handed over.
        page: The live page. Every action goes through it and nothing else here
            touches a browser.
        decide: Which operation, which element - one request, two answers.
        generate: What to type, asked only when an operation needs text.
        policy: The ceiling, the confidence floor and whether to send pictures.
        call_id: Which `browse_page` call this is, so a surface can keep two
            browses in one turn apart.
        sink: Where the frames go, or `None` on a surface that cannot show them.

    Returns:
        The outcome, the text to answer with, and how many steps it took. Never
        raises for a page's behaviour - a page that cannot be worked with is
        `blocked`, which is an answer.
    """

    async def emit(event: BrowserEvent) -> None:
        """Send one frame, or drop it on a surface that cannot show any.

        The frame is built by the caller rather than from keyword arguments
        here. A `**fields` splat into a typed model reads as tidier and is not
        checkable - every field arrives as `object` - and these frames are the
        one part of the capability a second program parses.
        """
        if sink is not None:
            await sink(event)

    first = await page.snapshot()
    await emit(
        BrowserEvent(
            kind="browser_opened",
            call_id=call_id,
            step=0,
            url=first.url,
            title=first.title,
            goal=goal,
            max_steps=policy.max_steps,
        )
    )

    history: tuple[str, ...] = ()
    recent: list[str] = []
    snapshot = first

    for step in range(1, policy.max_steps + 1):
        if step > 1:
            snapshot = await page.snapshot()

        if policy.preview:
            image = await page.screenshot()
            if image is not None:
                await emit(
                    BrowserEvent(
                        kind="browser_frame",
                        call_id=call_id,
                        step=step,
                        url=snapshot.url,
                        title=snapshot.title,
                        image=image,
                    )
                )

        choice = await decide(goal, snapshot, history)
        element = _element_at(snapshot, choice.index)
        await emit(
            BrowserEvent(
                kind="browser_step",
                call_id=call_id,
                step=step,
                url=snapshot.url,
                title=snapshot.title,
                operation=choice.operation,
                target=element.label if element is not None else None,
                confidence=choice.confidence,
            )
        )

        if choice.operation == "DONE":
            return await _finish(
                emit,
                call_id=call_id,
                outcome="done",
                step=step,
                text=await page.read(),
                detail="The goal was reached.",
                snapshot=snapshot,
            )

        if choice.operation == "BLOCKED":
            return await _finish(
                emit,
                call_id=call_id,
                outcome="blocked",
                step=step,
                text=await page.read(),
                detail="The engine found no available action that serves the goal.",
                snapshot=snapshot,
            )

        if choice.confidence is not None and choice.confidence < policy.min_confidence:
            return await _finish(
                emit,
                call_id=call_id,
                outcome="blocked",
                step=step,
                text=await page.read(),
                detail=(
                    f"The engine's pick scored {choice.confidence:.2f}, below this "
                    f"agent's {policy.min_confidence:.2f} floor."
                ),
                snapshot=snapshot,
            )

        signature = _signature(snapshot, choice)
        recent.append(signature)
        if recent[-REPEAT_LIMIT:].count(signature) == REPEAT_LIMIT:
            return await _finish(
                emit,
                call_id=call_id,
                outcome="blocked",
                step=step,
                text=await page.read(),
                detail=(
                    f"The same action was chosen {REPEAT_LIMIT} times running "
                    f"without changing the page."
                ),
                snapshot=snapshot,
            )

        # Dispatched on the operation, never on whether an element came back. A
        # SCROLL that also names a target is a decision the model is allowed to
        # make, and routing it by the target's presence would scroll by typing.
        if choice.operation in _NEEDS_ELEMENT:
            if element is None:
                return await _finish(
                    emit,
                    call_id=call_id,
                    outcome="blocked",
                    step=step,
                    text=await page.read(),
                    detail=(
                        f"The engine chose {choice.operation} without an element to apply it to."
                    ),
                    snapshot=snapshot,
                )
            try:
                history += (
                    await _act_on_element(page, choice.operation, element, goal, history, generate),
                )
            except StaleElement as refused:
                # The page moved between the snapshot and the decision, or the
                # two answers did not go together. Either way the action did not
                # happen, and the next snapshot describes what is there now - so
                # this is one wasted step with a reason the model can read, not
                # the end of the browse. The repeat guard is what stops a page
                # that does this for ever.
                history += (f"refused: {refused}",)
        else:
            history += (await _act_on_page(page, choice.operation),)
        await page.settle()

    return await _finish(
        emit,
        call_id=call_id,
        outcome="exhausted",
        step=policy.max_steps,
        text=await page.read(),
        detail=f"Stopped after the {policy.max_steps}-step ceiling without reaching the goal.",
        snapshot=snapshot,
    )


def _signature(snapshot: Snapshot, choice: Choice) -> str:
    """What makes one step distinguishable from the step before it.

    Three things beyond the operation and the element, each answering a way the
    guard was wrong with less:

    *The scroll position*, because scrolling down a long page is the same URL and
    the same operation three times running, and it is progress.

    *What the page offers*, because a URL is not a state. A wizard, a paginated
    table and a filter that rewrites its results in place all present `Next` at
    the same index on the same address - and each click advanced the flow.
    Without this the third such step is refused as a loop having in fact worked
    twice.

    **Roles and labels, and deliberately not values or the page's text.** Both
    were in here and both had to come out, because each made the guard weaker
    than the URL alone: a field's value changes the moment it is typed into, so
    typing the same thing ten times read as ten different states; and the text of
    any page with an autocomplete, a clock or a carousel on it differs every
    step, so nothing on such a page could ever repeat. Measured against a live
    Wikipedia: with the text in the signature, eight identical `TYPE_TEXT` steps
    ran to the ceiling unremarked.

    What that costs is honest and bounded: a page whose *labels* churn - a list
    of suggestions appearing under a search box - is not caught by this guard,
    and `max_steps` is what stops it. A guard that cannot be fooled by a dynamic
    page is a guard that refuses static ones.

    Hashed rather than carried, because this is compared and never read.
    """
    offered = "\u241f".join(f"{element.role}:{element.label}" for element in snapshot.elements)
    state = f"{snapshot.url}|{snapshot.scroll_y}|{offered}"
    return f"{sha256(state.encode()).hexdigest()}|{choice.operation}|{choice.index}"


def _element_at(snapshot: Snapshot, index: int | None) -> Element | None:
    """The element a decision picked, or `None` when it picked nothing.

    `None` for an index the snapshot does not hold as well, which is not
    defensive: when only one element is in view there is no pick-one to answer,
    the loop resolves the target itself, and an operation needing an element can
    arrive with none.
    """
    if index is None:
        return None
    for element in snapshot.elements:
        if element.index == index:
            return element
    return None


_NEEDS_ELEMENT = frozenset({"CLICK", "TYPE_TEXT", "SELECT"})
"""The operations that are meaningless without something to apply them to."""


async def _act_on_page(page: PageSession, operation: str) -> str:
    """Carry out the operations that address the page rather than an element.

    Returns:
        The history line describing what was done, which the next decision reads
        as "already done".
    """
    if operation == "SCROLL":
        await page.scroll()
        return "scrolled down one viewport"
    await page.settle()
    return "waited for the page to settle"


async def _act_on_element(
    page: PageSession,
    operation: str,
    element: Element,
    goal: str,
    history: tuple[str, ...],
    generate: Generate,
) -> str:
    """Carry out one operation against one element.

    The returned line says what was acted on rather than that something was:
    "clicked button: Accept all" is what stops the next step accepting the same
    banner again, and "clicked element 7" would not.

    Returns:
        The history line describing what was done.
    """
    if operation == "CLICK":
        await page.click(element)
        return f"clicked {element.role}: {element.label}"
    if operation == "SELECT":
        chosen = await generate(goal, element, history)
        await page.select(element, chosen)
        return f"chose {chosen!r} in {element.role}: {element.label}"
    text = await generate(goal, element, history)
    await page.type_text(element, text)
    # The value is deliberately not in this line. Every history entry is sent to
    # the decision model on the next step, and that endpoint is configured
    # separately and may be a third party - so a password, an address or anything
    # else the host model wrote into a field would be disclosed to it, which is
    # not what the data-protection inventory says it receives. What the next
    # decision needs is that the field is filled, not what with.
    return f"filled {element.role}: {element.label}"


async def _finish(
    emit: Callable[[BrowserEvent], Awaitable[None]],
    *,
    call_id: str,
    outcome: BrowseOutcome,
    step: int,
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
            step=step,
            url=snapshot.url,
            title=snapshot.title,
            outcome=outcome,
            detail=detail,
        )
    )
    return BrowseResult(outcome=outcome, text=text, steps=step)
