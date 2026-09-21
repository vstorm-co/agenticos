"""The live page, over the Chrome DevTools Protocol.

The only module in this package that needs a browser, and it is kept thin for
exactly that reason: everything that decides anything - which elements may be
chosen, which operation to carry out, when to stop, where the agent may go - lives
in a module that runs without one. What is here is I/O and the one piece of
JavaScript that reads a page.

`cdp-use` is imported inside the functions that use it. The `browser` extra is
absent from a default install and from CI, and the capability has to register,
enumerate its tool and build its toolset without it - so an agent bound to it on a
deployment that never installed the extra fails that one tool with an install
line, rather than failing to start.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from app.agents.capabilities.browser_choice._elements import (
    Element,
    Snapshot,
    candidates,
    clean_label,
    page_text,
)
from app.agents.capabilities.browser_choice._endpoint import (
    EndpointError,
    domain_allowed,
    version_url,
    websocket_url,
)

MISSING_EXTRA = (
    "Browser automation is bound to this agent but the 'browser' extra is not "
    "installed. Install it with: pip install 'agenticos[browser]'."
)

READ_LIMIT = 20_000
"""How much of a page's text a finished browse answers with.

A page is not a document: a long article's text is the answer, and a search
results page's text is mostly navigation. Bounded because the whole of it goes
into the calling model's context, where an unbounded tool result is how one
`browse_page` ends a conversation.
"""

_CONTEXT_GONE = "Execution context was destroyed"
"""What CDP answers while a navigation is replacing the page under a command."""

_EVAL_ATTEMPTS = 5
_READY_ATTEMPTS = 20
_EVAL_BACKOFF = 0.25
_SETTLE_MS = 400
_VIEWPORT_RATIO = 0.75
"""Viewport height as a fraction of its width - a 4:3 window, not a phone.

Taller shows more of a page per step and costs more of the decision model's
attention on each; this is the shape a laptop actually has.
"""
"""How long to wait, and how often, for a page that is still arriving.

Measured against a live Chromium rather than guessed: a `Target.createTarget`
with a URL begins navigating before the session is attached, so the first
`Runtime.evaluate` lands in a context that is already gone.
"""

COLLECT_JS = """
(() => {
  const SELECTOR = [
    'a[href]', 'button', 'input:not([type=hidden])', 'select', 'textarea',
    '[role=button]', '[role=link]', '[role=checkbox]', '[role=radio]',
    '[role=tab]', '[role=menuitem]', '[role=option]', '[role=switch]',
    '[contenteditable=""]', '[contenteditable=true]',
  ].join(',');
  const roleOf = (el) => {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === 'a') return 'link';
    if (tag === 'input') return (el.type || 'text') === 'text' ? 'textbox' : el.type;
    if (tag === 'textarea') return 'textbox';
    if (tag === 'select') return 'dropdown';
    return tag;
  };
  const labelOf = (el) =>
    el.getAttribute('aria-label') ||
    (el.innerText || '').trim() ||
    el.getAttribute('placeholder') ||
    el.getAttribute('title') ||
    el.getAttribute('alt') ||
    el.getAttribute('name') ||
    el.value ||
    '';
  // A selector that resolves to this element and no other. An id when the
  // document really has one of it; otherwise the nth-of-type chain up to body,
  // which is what makes an action verifiable after the page has re-rendered.
  const pathOf = (el) => {
    if (el.id) {
      const byId = '#' + CSS.escape(el.id);
      try { if (document.querySelectorAll(byId).length === 1) return byId; } catch (e) {}
    }
    const parts = [];
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      const tag = node.tagName.toLowerCase();
      if (tag === 'html') break;
      const parent = node.parentElement;
      if (!parent) break;
      const kin = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
      parts.unshift(kin.length > 1 ? tag + ':nth-of-type(' + (kin.indexOf(node) + 1) + ')' : tag);
    }
    return parts.join(' > ');
  };
  const out = [];
  for (const el of document.querySelectorAll(SELECTOR)) {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    if (r.bottom < 0 || r.top > window.innerHeight) continue;
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') continue;
    if (el.disabled) continue;
    const isSelect = el.tagName === 'SELECT';
    out.push({
      role: roleOf(el),
      label: labelOf(el),
      path: pathOf(el),
      value: (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')
        ? (el.value || '')
        : (isSelect ? (el.selectedOptions[0] ? el.selectedOptions[0].label : '') : ''),
      // A native dropdown's choices travel with it rather than as rows of their
      // own: a country list would otherwise be the whole table.
      options: isSelect
        ? Array.from(el.options).map((o) => (o.label || o.value || '').trim()).filter(Boolean)
        : [],
    });
  }
  return JSON.stringify({
    url: location.href,
    title: document.title,
    text: document.body ? document.body.innerText : '',
    scrollY: window.scrollY,
    scrollHeight: document.documentElement.scrollHeight,
    viewportHeight: window.innerHeight,
    elements: out,
  });
})()
"""
"""What a page looks like to the loop, collected in the page's own runtime.

Deliberately geometric rather than semantic. The accessibility tree is the richer
source and it is also the one a page controls: `aria-label` is an author's
sentence, and a hostile page's accessibility tree is a hostile page's prose. A
bounding rectangle that is on screen, non-zero and not disabled is a fact about
what a person could press.

Elements arrive in document order and are numbered in Python, so the table the
model reads and the truncation that bounds it cannot disagree about which element
is which. Each carries a selector as well, because the number is only meaningful
against the snapshot it came from and an action happens later than that.

The page's own visible text comes back too. Without it the model cannot tell that
the goal has been reached - a price, a confirmation, "no results" are text, not
elements - and `DONE` would be a guess.
"""

_SELECT_JS = """
(() => {
  const el = document.querySelector(%(path)s);
  if (!el || el.tagName !== 'SELECT') return JSON.stringify({chosen: false});
  const wanted = String(%(value)s).trim().toLowerCase();
  const option = Array.from(el.options).find(
    (o) => (o.label || '').trim().toLowerCase() === wanted ||
           (o.value || '').trim().toLowerCase() === wanted
  );
  if (!option) return JSON.stringify({chosen: false});
  el.value = option.value;
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
  return JSON.stringify({chosen: true});
})()
"""
"""Choosing an option the way a person's choice reaches the page's listeners."""

VERIFY_JS = """
(() => {
  const el = document.querySelector(%(path)s);
  if (!el) return JSON.stringify({found: false});
  const r = el.getBoundingClientRect();
  const explicit = el.getAttribute('role');
  const tag = el.tagName.toLowerCase();
  const role = explicit
    ? explicit
    : tag === 'a' ? 'link'
    : tag === 'input' ? ((el.type || 'text') === 'text' ? 'textbox' : el.type)
    : tag === 'textarea' ? 'textbox'
    : tag === 'select' ? 'dropdown'
    : tag;
  return JSON.stringify({
    found: true,
    role: role,
    label: (el.getAttribute('aria-label') || (el.innerText || '').trim() ||
            el.getAttribute('placeholder') || el.getAttribute('title') ||
            el.getAttribute('alt') || el.getAttribute('name') || el.value || ''),
    x: r.left + r.width / 2,
    y: r.top + r.height / 2,
    onscreen: r.width >= 1 && r.height >= 1 && r.bottom >= 0 && r.top <= window.innerHeight,
  });
})()
"""
"""Where an element is *now*, and whether it is still the one that was offered.

The decision model answers after the snapshot was taken, which on a page that
re-renders is long enough for everything to move. Acting on the centre the
snapshot recorded is how a click lands on whatever slid into that position -
which is an action on an element that was never in the candidate table, and the
whole bounded-action property gone. So every action resolves the selector again,
compares what it found against what was offered, and uses the fresh coordinates.
"""


def parse_snapshot(raw: object, cap: int) -> Snapshot:
    """One `Runtime.evaluate` result as the snapshot the loop consumes.

    Kept separate from the call that produces it so the parsing - the numbering,
    the truncation and the label cleaning that decide what the model may pick -
    is tested against a payload rather than against a browser.

    Args:
        raw: The JSON string the collector returned, already unwrapped from the
            CDP envelope.
        cap: How many elements may be offered this step.

    Returns:
        The page, with at most `cap` elements numbered from zero.

    Raises:
        EndpointError: The page answered with something that is not the
            collector's payload, which means the evaluate did not run.
    """
    payload: Any = json.loads(raw) if isinstance(raw, str) else None
    if not isinstance(payload, dict):
        raise EndpointError("The page did not return a snapshot; the collector did not run.")
    found = payload.get("elements", [])
    elements = tuple(
        Element(
            index=index,
            role=clean_label(str(item.get("role", "element"))),
            label=clean_label(str(item.get("label", ""))),
            path=str(item.get("path", "")),
            value=clean_label(str(item["value"])) if item.get("value") else None,
            options=tuple(clean_label(str(option)) for option in item.get("options") or ()),
        )
        for index, item in enumerate(found)
    )
    return Snapshot(
        url=str(payload.get("url", "")),
        title=str(payload.get("title", "")),
        elements=candidates(elements, cap),
        text=page_text(str(payload.get("text") or "")),
        scroll_y=float(payload.get("scrollY", 0.0)),
        scroll_height=float(payload.get("scrollHeight", 0.0)),
        viewport_height=float(payload.get("viewportHeight", 0.0)),
    )


@dataclass(frozen=True, slots=True)
class PagePolicy:
    """What the page layer was configured with, separate from what the loop was.

    `allowed_domains` is enforced here rather than in the loop because it is a
    property of navigation, not of deciding: a click that follows a redirect off
    the allowlist has to be caught where the URL is read, and the loop never reads
    one it did not get from here.
    """

    allowed_domains: list[str] | None
    candidate_cap: int
    preview: bool
    preview_width: int


class DomainRefused(RuntimeError):
    """The browser ended up somewhere the agent's allowlist does not permit."""


class StaleElement(RuntimeError):
    """The element a decision named is not the element that is there now.

    Raised rather than worked around, and read by the loop as one step's refusal
    rather than the browse's end: the page moved, the next snapshot describes
    where it moved to, and the model gets to choose again. What must not happen
    is the action going ahead on whatever is at those coordinates instead.
    """


class CdpPage:
    """A page driven over CDP, implementing the loop's `PageSession`.

    Every method here is one or two protocol commands and no decisions. The
    coordinates an action uses come from the snapshot that offered the element,
    never from re-resolving an index against the page as it is now - a page that
    re-rendered between the snapshot and the click has renumbered everything, and
    clicking "element 7" after that is clicking whatever moved into seventh place.
    """

    def __init__(self, client: Any, session_id: str, policy: PagePolicy) -> None:
        self._client = client
        self._session = session_id
        self._policy = policy

    async def _evaluate(  # pragma: no cover - needs a live browser
        self, expression: str, *, await_promise: bool = False
    ) -> Any:
        """Run JavaScript in the page, surviving a navigation under it.

        A navigation destroys the page's execution context, and CDP answers
        `Execution context was destroyed` to anything already in flight or sent
        before the new one exists. That is not an error here: a click on a link is
        supposed to navigate, and the step after it has to read the page it
        landed on. Retried a handful of times against a live browser rather than
        guessed at - a fixed sleep is the same bet with no evidence.

        Returns:
            The `result` object CDP answered with.

        Raises:
            RuntimeError: The page never came back, or failed for any other reason.
        """
        for attempt in range(_EVAL_ATTEMPTS):
            try:
                answer = await self._client.send.Runtime.evaluate(
                    params={
                        "expression": expression,
                        "returnByValue": True,
                        "awaitPromise": await_promise,
                    },
                    session_id=self._session,
                )
            except RuntimeError as exc:
                if _CONTEXT_GONE not in str(exc) or attempt == _EVAL_ATTEMPTS - 1:
                    raise
                await asyncio.sleep(_EVAL_BACKOFF)
                continue
            return answer.get("result", {})
        raise RuntimeError(_CONTEXT_GONE)  # unreachable; the loop returns or raises

    async def snapshot(self) -> Snapshot:  # pragma: no cover - needs a live browser
        """The page as it is now, refused if it has left the allowlist."""
        result = await self._evaluate(COLLECT_JS)
        snapshot = parse_snapshot(result.get("value"), self._policy.candidate_cap)
        if not domain_allowed(snapshot.url, self._policy.allowed_domains):
            raise DomainRefused(
                f"The browser navigated to {snapshot.url}, which this agent's "
                f"allowed domains do not cover."
            )
        return snapshot

    async def _locate(  # pragma: no cover - needs a live browser
        self, element: Element
    ) -> tuple[float, float]:
        """Where `element` is now, having checked it is still the same element.

        The decision model answered against a snapshot, and a page that
        re-rendered since has moved everything. Resolving the selector again and
        comparing what came back is what keeps an action on the element that was
        offered rather than on whatever took its place - and the coordinates
        returned are the fresh ones, because the recorded centre is exactly the
        stale fact that would send a click somewhere else.

        Returns:
            The element's centre, in viewport coordinates.

        Raises:
            StaleElement: It is gone, off screen, or no longer describes itself
                the way the candidate table said it did.
        """
        if not element.path:
            raise StaleElement(
                f"The engine chose {element.role}: {element.label}, which this "
                f"page offers no way to address."
            )
        # `%` formatting rather than an f-string: the selector is interpolated
        # into JavaScript, so it goes in as a JSON string literal and cannot
        # close the quote it sits in.
        raw = await self._evaluate(VERIFY_JS % {"path": json.dumps(element.path)})
        found: Any = json.loads(str(raw.get("value") or "{}"))
        if not found.get("found") or not found.get("onscreen"):
            raise StaleElement(
                f"{element.role}: {element.label} is no longer on the page where it was offered."
            )
        moved_role = clean_label(str(found.get("role", "")))
        moved_label = clean_label(str(found.get("label", "")))
        if (moved_role, moved_label) != (element.role, element.label):
            raise StaleElement(
                f"The page changed under the decision: {element.role}: "
                f"{element.label} is now {moved_role}: {moved_label}."
            )
        return float(found.get("x", 0.0)), float(found.get("y", 0.0))

    async def click(self, element: Element) -> None:  # pragma: no cover - needs a live browser
        """Press an element, where it is now rather than where it was."""
        x, y = await self._locate(element)
        for event in ("mousePressed", "mouseReleased"):
            await self._client.send.Input.dispatchMouseEvent(
                params={"type": event, "x": x, "y": y, "button": "left", "clickCount": 1},
                session_id=self._session,
            )

    async def type_text(  # pragma: no cover - needs a live browser
        self, element: Element, text: str
    ) -> None:
        """Focus a field and enter `text`, replacing whatever it held.

        Refuses an element that cannot hold text before it touches it. Typing
        begins with a click to focus, so `TYPE_TEXT` aimed at a link would follow
        the link and only then fail - performing an action nobody chose. The
        operation and the target are two independent answers from the model, so
        that pair is reachable and has to be refused rather than attempted.

        Raises:
            StaleElement: The element moved, or was never one that can be typed in.
        """
        if not element.editable:
            raise StaleElement(
                f"TYPE_TEXT cannot be carried out on {element.role}: "
                f"{element.label}, which is not a field that holds text."
            )
        x, y = await self._locate(element)
        for event in ("mousePressed", "mouseReleased"):
            await self._client.send.Input.dispatchMouseEvent(
                params={"type": event, "x": x, "y": y, "button": "left", "clickCount": 1},
                session_id=self._session,
            )
        await self._client.send.Input.dispatchKeyEvent(
            params={"type": "keyDown", "key": "a", "code": "KeyA", "modifiers": 2},
            session_id=self._session,
        )
        await self._client.send.Input.insertText(params={"text": text}, session_id=self._session)

    async def select(  # pragma: no cover - needs a live browser
        self, element: Element, value: str
    ) -> None:
        """Choose `value` in a native dropdown, and fire what a person's choice fires.

        Not a click. Clicking a `<select>` opens Chromium's own popup, whose
        options are not in the DOM at all - so the next snapshot shows the same
        untouched dropdown, and a form that needs one choice loops until the
        repeat guard stops it. The value is set on the element and `input` and
        `change` are dispatched, which is what every listener on that form is
        waiting for.

        Matching is on the option's visible label first and its value second,
        case-folded, because the model was shown labels.

        Raises:
            StaleElement: The element moved, is not a dropdown, or has no such option.
        """
        if element.role != "dropdown":
            raise StaleElement(
                f"SELECT cannot be carried out on {element.role}: {element.label}, "
                f"which is not a dropdown."
            )
        await self._locate(element)
        script = _SELECT_JS % {"path": json.dumps(element.path), "value": json.dumps(value)}
        answer = await self._evaluate(script)
        if not json.loads(str(answer.get("value") or "{}")).get("chosen"):
            raise StaleElement(
                f"{element.label} has no option matching {value!r}; its choices "
                f"are the ones listed with it."
            )

    async def scroll(self) -> None:  # pragma: no cover - needs a live browser
        """Move one viewport down."""
        await self._evaluate("window.scrollBy(0, window.innerHeight * 0.9)")

    async def settle(self) -> None:  # pragma: no cover - needs a live browser
        """Wait for whatever the last action started, then for the page to be ready.

        Two halves, because the last action may or may not have navigated. The
        pause gives a click that only changed the DOM time to finish; the
        readiness poll is what covers a click that replaced the page, where the
        context the pause ran in no longer exists.
        """
        await self._evaluate(f"new Promise(r => setTimeout(r, {_SETTLE_MS}))", await_promise=True)
        for _ in range(_READY_ATTEMPTS):
            state = (await self._evaluate("document.readyState")).get("value")
            if state in {"interactive", "complete"}:
                return
            await asyncio.sleep(_EVAL_BACKOFF)

    async def screenshot(self) -> str | None:  # pragma: no cover - needs a live browser
        """The viewport as a JPEG `data:` URL, or `None` when previews are off.

        Bounded by `preview_width` without resizing anything, because the
        viewport *is* `preview_width` - set once on the session in `open_page` -
        and `captureBeyondViewport` is off. One number decides how wide the page
        renders and how wide the picture is, which is also what keeps the frame a
        person watches identical to the page the model was shown.
        """
        if not self._policy.preview:
            return None
        shot = await self._client.send.Page.captureScreenshot(
            params={
                "format": "jpeg",
                "quality": 60,
                "captureBeyondViewport": False,
                "optimizeForSpeed": True,
            },
            session_id=self._session,
        )
        data = shot.get("data")
        return f"data:image/jpeg;base64,{data}" if data else None

    async def read(self) -> str:  # pragma: no cover - needs a live browser
        """The page's readable text, bounded, and only where the allowlist covers it.

        Checked here as well as in `snapshot`, which is not belt and braces: a
        browse ends by reading the page, and the last step can be a click that
        navigated somewhere the allowlist does not cover. Without this check that
        page's text is the tool's answer - the content the allowlist exists to
        keep out, delivered into the calling model's context, on the one path that
        takes no further snapshot.

        The allowlist cannot stop the navigation itself: a browser follows a link
        or a redirect before anything here is asked. What it can do is refuse to
        act on that page and refuse to repeat it, which is what this and
        `snapshot` together enforce.

        Returns:
            The page's text, or a sentence saying it was withheld and why.
        """
        url = (await self._evaluate("location.href")).get("value")
        if not domain_allowed(str(url or ""), self._policy.allowed_domains):
            return (
                f"[The browse ended on {url}, which this agent's allowed domains "
                f"do not cover. Its content was not read.]"
            )
        result = await self._evaluate("document.body ? document.body.innerText : ''")
        return str(result.get("value") or "")[:READ_LIMIT]


@asynccontextmanager
async def open_page(  # pragma: no cover - needs a live browser
    *, cdp_url: str, start_url: str, policy: PagePolicy
) -> AsyncIterator[CdpPage]:
    """Attach to a browser, open one tab on `start_url`, and close it again.

    The tab is created and closed by this context manager, so a browse leaves the
    browser as it found it - a long-lived browser service accumulating one
    abandoned tab per run is the failure mode a shared endpoint actually has.

    Raises:
        RuntimeError: The `browser` extra is not installed.
        DomainRefused: `start_url` is outside the agent's allowlist.
        EndpointError: The endpoint is not a Chromium DevTools endpoint.
    """
    if not domain_allowed(start_url, policy.allowed_domains):
        raise DomainRefused(f"{start_url} is outside this agent's allowed domains.")
    try:
        import httpx

        # ty: `cdp-use` arrives with the `browser` extra, which a default install
        # and CI deliberately do not have - the whole design of this package is
        # that everything but this function works without it. The import is
        # inside the `try` for the same reason, and the `except` below is what a
        # deployment missing the extra actually gets.
        from cdp_use import CDPClient  # ty: ignore[unresolved-import]
    except ImportError as exc:
        raise RuntimeError(MISSING_EXTRA) from exc

    if cdp_url.startswith(("ws://", "wss://")):
        socket = cdp_url
    else:
        async with httpx.AsyncClient(timeout=10.0) as http:
            response = await http.get(version_url(cdp_url))
            response.raise_for_status()
            socket = websocket_url(cdp_url, response.json())

    client = CDPClient(socket)
    await client.start()
    target: str | None = None
    try:
        # The tab is created empty and navigated afterwards, which is not a
        # detail: `createTarget` with a URL starts navigating before there is a
        # session to attach, so the first command lands in an execution context
        # the navigation has already destroyed. Measured against a live Chromium.
        created = await client.send.Target.createTarget(params={"url": "about:blank"})
        target = created["targetId"]
        attached = await client.send.Target.attachToTarget(
            params={"targetId": target, "flatten": True}
        )
        session = attached["sessionId"]
        # Neither takes parameters, and `Runtime.enable` is typed `params: None` -
        # an empty dict is accepted at run time and is still the wrong call.
        await client.send.Page.enable(session_id=session)
        await client.send.Runtime.enable(session_id=session)
        # The viewport, before anything is loaded. A headless Chromium defaults to
        # 800x600, which decides more than how the pictures look: the element
        # table holds what is *on screen*, so a short viewport hides a search box
        # below the fold and the loop spends a step scrolling to what a person
        # would have seen without moving. `preview_width` sets both, so the frame
        # a person watches is the page the model was shown.
        await client.send.Emulation.setDeviceMetricsOverride(
            params={
                "width": policy.preview_width,
                "height": round(policy.preview_width * _VIEWPORT_RATIO),
                "deviceScaleFactor": 1,
                "mobile": False,
            },
            session_id=session,
        )
        page = CdpPage(client, session, policy)
        await client.send.Page.navigate(params={"url": start_url}, session_id=session)
        await page.settle()
        yield page
    finally:
        if target is not None:
            await client.send.Target.closeTarget(params={"targetId": target})
        await client.stop()
