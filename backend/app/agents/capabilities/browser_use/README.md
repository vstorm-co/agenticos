# Web browser (`browser_use`)

One tool, `browse_web`. It opens a URL in a Chromium the operator runs and then
repeats three things: read the page into a numbered table of the elements a person
could act on, ask the run's own model for one step, carry the step out. It stops
when the model says the task is done or cannot be done, or at the call's step
ceiling - and a ceiling is a pause, not an end (#2127).

Beside it, the agent's own hands on the same tab: `browser_open`, `browser_read`,
`browser_click`, `browser_type`, `browser_select`, `browser_scroll` and
`browser_back` (`_direct.py`). One action a call, chosen by the run's model in its
own turn and answered with the page after it - no second request per step, which
is where `browse_web` spends 85% of a step. They narrate exactly as a loop step
does, under the live view the first direct call opened, so the panel grows instead
of multiplying; the run's end finishes that view.

## Why the loop is this repository's

There used to be two browsers. `browser_use` delegated to the `browser-use`
library, which could never be installed beside the platform: 0.13.x hard-pins
`openai`, `google-genai` and `requests` below what Pydantic AI needs, and uv
refuses to lock even an optional extra whose pins conflict with the base ones.
`browser_choice` was this repository's loop, but its steps were picked by a
TypeSafe model behind a second vendor and a second key.

Now there is one. The id stayed `browser_use`, because ids are in every published
spec; `browser_choice` bindings load as this one (spec version 13). The loop is the
one `browser_choice` built - the element table, the allowlist, the repeat guard,
the live frames - and the step is browser-use's shape, answered by the run's own
model:

```python
class Step(BaseModel):
    evaluation: str  # did the previous action work?
    memory: str  # what to carry to every later step
    next_goal: str  # what this action is for
    action: Click | TypeText | Select | Scroll | Navigate | GoBack | Wait | Done | Blocked
```

Judging the last action before choosing the next is what stops the model
pressing a button that did nothing a second time, and `memory` is what lets a
forty-step task keep a fact it read on step three without the page history in
every prompt. `cdp-use` speaks the protocol; nothing else is a dependency.

## The decisions everything else follows from

**An action names a row, never a selector.** Every element the model can act on is
a numbered row of a table this deployment built from the live DOM. A page cannot
offer an action by describing one: the worst a hostile page can do is persuade the
model to press something the page genuinely has. The system prompt still says page
text is untrusted data; what bounds the damage is the shape of the answer.

That is not the same as safe. "Delete account" is an action a page genuinely
offers.

**Which is why the two `side_effecting` flags disagree.** The capability's is true,
so the console badges it and an operator can gate it. The tool's is false, so a
browse is not held by default. An approval on a browse arrives before the first
page is fetched, on a task in natural language: it asks somebody to approve
actions nobody can see yet. What stands in its place is that a browse is
*watchable* - the console draws it while it runs, and every step names what it
pressed and why - plus `allowed_domains`, which bounds where it can go at all. An
operator who wants the gate sets `tool_approval` on the binding.

**`blocked` is an answer.** A sign-in wall, a captcha, a page that does not contain
what was asked for - the model says so and the browse ends with an outcome a
person can read. Four outcomes, no fifth: `done`, `blocked`, `exhausted`,
`failed`.

**One tab per run.** The toolset is entered by the run and keeps the tab between
calls, so a second `browse_web` without `start_url` continues where the first
stopped - signed in, half way through a form, with the model's memory - and the
tab is closed when the run ends. A call with a `start_url` starts a new task in
the same tab. The toolset is sequential, because two browses at once would drive
the one tab in turns.

## The endpoint

`cdp_url` points at a browser service the operator runs, never a process in the
API image. It is tenant-controlled - it lives in a spec - so it is checked against
`BROWSER_CDP_ALLOWED_HOSTS` at publish. Chromium answers its DevTools endpoint only to a `Host` that is an address,
so a plain `http`/`ws` endpoint given by name is resolved once and reached by
address (`pin_host`); TLS endpoints keep their name for the certificate.

One host is refused even when the allowlist names it: the host of
`ARTIFACT_RENDER_CDP_URL`. That is the browser `preview_artifact` draws people's
pages in - deployment config, never an author's - so listing it by mistake must
not hand it to every browsing agent.

Each browse gets its own browser context, disposed with the tab, so one person's
cookies are never the next caller's.

## Where a person comes in, and how a browse reaches the web

The model can `ask_person` for a sign-in or a captcha; whoever the run acts for,
or someone who may edit the agent, takes the tab over from the live view and
hands it back, and what they type is never recorded (#2128). A sign-in kept on
hand-back is reused by that person's later browses of the same site (#2129).
Compose's browser is a full Chromium under Xvfb that sites read as a desktop
one, and an agent's binding can send its browses through a proxy or run them in a
hosted browser over CDP (`_route.py`, #2130).

## Interactive browser lifetime and readiness

Direct tools keep one preview stream open across model turns within the run.
The stream stops before the tab closes or `browse_web` takes over its narration.
Pages belong to the run and close at its end. Private conversations keep a
user-sealed checkpoint in Redis for one hour, containing tab URLs, cookies and
local storage. `browser_read` restores it into new isolated contexts with fresh
element numbers; DOM state, unsaved forms and navigation history are not restored.
Hosted browsers do not receive checkpoints. Explicit tools open, list, switch and
close up to eight tabs. Native tabs retain their existing bounded lifecycle.
`_preview.py` owns the stream and polls location independently of model calls.
Only authenticated image-view sockets count as viewers; trace consumers and a
resumable chat buffer do not. Images stop without a viewer and resume on return.
Metadata updates preserve the latest JPEG for viewers opening the live view.
A final image is kept even without a viewer; it does not enter the chat stream.
DOM tools and DOM-only `browse_web` steps do not capture screenshots. The owned
preview stream paints independently; teardown joins it before capturing one final
image and sending completion. Vision decisions still await the image they consume.

`WebBrowser.before_model_request` copies older direct-tool reports without their
obsolete element tables. The latest table, page text, URLs and action outcomes
remain intact; the persisted transcript is unchanged. Factory ordering puts this
after compaction and before system reminders. MCP tool schemas are unchanged.

Readiness tracks visible main content and dialogs, ignoring presentation-only
attribute changes and activity outside the content. It retains bounded DOM quiet
and load waits. A newly empty direct-tool read gets one bounded readiness retry
before its result is returned, including when navigation replaces the document.

The console opens a full-height browser side panel automatically, with compact
transcript links to reopen it after closing.

While a person holds the tab, input is consumed independently of preview capture.
They can navigate, move through history and reload within `allowed_domains`.
Navigation checks document identity rather than requiring a different URL;
ordinary actions wait for bounded document readiness and DOM stability.
A pending direct action is refused after a take-over so the model must read the
page again before choosing an element.


## Native conversation tabs

Desktop local DOM browsing uses `_native.py` and the shell's `native_browser.rs`.
The page is a real child WebView in the console panel, with no JPEG preview path.
Only its paired app resolves the opaque handle. The backend derives the tab scope
from organization, user, agent and conversation; a run holds an exclusive lease.
An owned heartbeat renews the lease every 30 seconds; it expires after two
minutes without renewal. Release preserves the private page, while explicit close, device disconnect or
bounded idle eviction destroys it. `browser_read` reattaches on a later run.
Changes to the domain policy require closing the old tab first.

The native DOM adapter preserves the collector and stale-element checks. A
context-local action marker guards DOM writes as well as input against a local
takeover; reading remains available. The page has only a one-way pause capability.
Console grants name their exact WebView rather than every child of their window.
Disabling `prefer_native_browser` selects Chromium compatibility.
Tasks with vision or locale/time-zone emulation retain the Chromium adapter,
including its per-run disposable profile. Scripted native input is not identical
to trusted CDP input, and remote viewers cannot render an owner's native page.

Images are published on a separate Redis channel, so trace consumers do not
receive or decode their base64 data. Remote preview delivery keeps one pending image and a bounded ordered narration
queue. A socket write exceeding two seconds, or a full narration queue, ends that
viewer with close code 1013. Reconnecting obtains a fresh snapshot. Images are
not also copied into the resumable chat buffer when a live-view socket owns them.
