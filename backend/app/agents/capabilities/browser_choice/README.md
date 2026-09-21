# Browser automation, choosing (`browser_choice`)

One tool, `browse_page`. It opens a URL in a Chromium the operator runs and then
repeats three things: read the page into a numbered table of the elements a person
could act on, ask a decision model which operation and which element, carry that
out. Only typing a field's value reaches a language model.

It exists beside `browser_use` rather than replacing it, and #1829 is where that
was argued. The short version: they answer different questions, and they fail
differently, so they document differently.

## The decision that everything else follows from

**The model chooses; it does not compose.** A browser agent that generates its
next action can emit any string, so a page's text is an instruction channel into
the model and the only defence is telling the model not to listen. This loop hands
the model a list built server-side from the live DOM and takes back one entry.
A page cannot offer an action by describing one, because the answer is
type-constrained to the options this deployment put in the list.

The prompt still says page text is untrusted data. What *enforces* it is the
shape of the question.

That is not the same as safe. "Delete account" is an action a page genuinely
offers. The action space is bounded, not harmless.

**Which is why the two `side_effecting` flags disagree here.** The capability's is
true, so the console badges it and an operator can gate it. The tool's is false,
so a browse is not held by default - and that is a decision rather than an
oversight. An approval on a browse arrives *before* the first page is fetched, on
a goal in natural language and a URL: it asks somebody to approve actions nobody
can see yet, which is consent without information, and the answer to it is almost
always yes. What stands in its place is that a browse is *watchable* - the console
draws it while it runs and every step names what was chosen and how sure the
engine was - plus `allowed_domains`, which bounds where it can go at all, and
`min_confidence`, which is the automatic form of the same instinct. An operator
who wants the gate sets `tool_approval` on the binding, which beats both flags.

**`BLOCKED` is an answer.** A sign-in wall, a consent gate, a captcha, a page that
simply does not contain what was asked for - the engine says so in the same breath
as any other step, and the browse ends with an outcome a person can read. Four
outcomes, no fifth: `done`, `blocked`, `exhausted`, `failed`. A loop that could
only succeed or time out would report a login wall and a crashed browser
identically.

## What this repository owns, and why it is not the library

`browser_use` is the `sandbox` arrangement: the library owns the browser agent,
this package owns the contract. Here it is the other way round. `cdp-use` speaks
the protocol and `TypeSafeModel` answers typed questions; the loop, the element
table, the allowlist and the stopping rules are in `_loop.py`, `_elements.py`,
`_questions.py` and `_endpoint.py`.

That is deliberate, and it is where the security property lives: an engine whose
action space is somebody else's loop is an engine whose action space is somebody
else's decision. It is also what makes the whole thing testable - every module but
`_page.py` runs without a browser, an account or a network.

#1829 proposed building on `browser-harness`. Read at 0.1.13 that package is a CLI
and a per-user daemon for attaching a coding agent to a developer's own Chrome:
synchronous helpers over an AF_UNIX socket, a PID file, a `SKILL.md`. It holds no
DOM snapshotter, so it would not have carried the element table either. `cdp-use`,
its own dependency, is the part that was wanted. The dependency note in
`pyproject.toml` has the measurements.

## What it deliberately does not do

**Launch a browser.** There is no `playwright` mode and no Chromium in the API
image. `cdp_url` points at a browser service an operator runs and isolates. A
browser in the application container widens the surface the platform itself runs
on, for nothing.

The field is not left blank for somebody to guess at, though. The Builder
prefills it from `BROWSER_CDP_ALLOWED_HOSTS` when exactly one host is allowed,
and hints the first one otherwise - an author is choosing from that list whether
the form says so or not, and a field that refuses at publish without ever saying
what it would accept wastes an afternoon. `agenticos cmd doctor` then answers the
other half: whether anything is actually listening. It reports rather than fails,
because the allowlist holds hosts and not ports, so the probe has to assume
Chromium's 9222 and an operator on another port is not broken.

**Decide for itself which browser it may drive.** The host must be on
`BROWSER_CDP_ALLOWED_HOSTS`, and an empty allowlist - the default - refuses the
capability outright. That is deliberately *not* `browser_use`'s arrangement,
which runs `cdp_url` through the SSRF guard (agenticos#33). The guard is the
right control for a webhook and the wrong one here, in both directions: it admits
only a *public* address, so it refuses the isolated service on the deployment's
own network that this file tells an operator to run - `http://browser:9222` in
the same compose project resolves privately and was rejected - while accepting a
CDP debugger exposed to the open internet, which is a worse posture than the one
it forbade. Measured, not argued: before this, the only endpoint that published
was a public IP.

What makes an allowlist the right shape is what `cdp_url` is. It lives in a spec,
which anyone holding `edit` on the agent writes, so the address is
tenant-controlled and the request is the deployment's - the same problem
`MEM0_ALLOWED_HOSTS` exists for, and the same answer. A vetted host needs no
address check; an unvetted one is refused whatever it resolves to. Matching is
exact and case-folded: a hostname is not a pattern, and `*.internal` on a
security allowlist is a wildcard somebody reads as narrower than it is.

**Rank the candidate set.** Truncation to `candidate_cap` is by document order and
nothing else. Scoring the elements by relevance to the goal would put the decision
this capability exists to make back inside an opaque function, and would make two
runs over one page offer different tables. The loop's answer to a page too dense
for the cap is to scroll.

**Share a browser context between callers.** Every browse gets one of its own,
disposed when it ends. On a long-lived browser shared by many callers - which is
the arrangement this capability tells an operator to run - the default context
keeps the cookie set when one person's agent signed in, and the next caller of
the same agent arrives already authenticated as them. Closing the tab does not
clear that; disposing the context does. There is deliberately no fallback if the
browser refuses one, because falling back to the default context is the leak.

**Send a field's contents anywhere.** Only whether it has any. Redacting the
history line was half a fix and read like a whole one: the next snapshot copied
`el.value` straight back out of every input, `render_table` printed it as
`[currently: ...]`, and the password the host model had just typed reached the
decision endpoint one step after being kept out of the history. The table says
`[filled]` now. A dropdown is the exception rather than an inconsistency - its
selected option is one of the options already listed beside it, and without it
the loop cannot tell a chosen list from an unchosen one.

**Let a browse off the web.** `domain_allowed` returns true for an agent with no
`allowed_domains`, and "anywhere" used to include `file:///etc/passwd` - which
`start_url` is written by a model, and which `read()` would then have handed back
as the answer. The scheme is checked before the host and whatever the allowlist
says.

**Read a form control's name off the control.** `<label for="email">Email</label>`
beside an `<input id="email">` is how a form is ordinarily written, and such an
input has no `innerText`, often no placeholder and no title - so the first version
of the collector handed the model an empty label and the model could not tell
which field it was being asked to fill. `el.labels` and `aria-labelledby` come
first now.

**Compute "what is this" twice.** The collector offers an element by role and
label and the verifier refuses to act on one whose role or label has changed, so
two copies of that computation are two chances for every element of some kind to
fail its own identity check. It happened within an hour of the first copy: the
collector learned that a `contenteditable` div is a textbox, the verifier did not,
and every rich-text editor was refused as "now a div". `_NAMING_JS` is
interpolated into both.

**Trust that the coordinates are reachable.** Resolving the selector proves the
element is still there; it does not prove nothing is on top of it. A consent
overlay, a sticky header or a transparent modal takes the press instead - an
action on a node that was never in the candidate table - so `elementFromPoint`
decides, and a descendant counts as a hit because a button's own label is what
sits at its centre.

**Let a click open a tab it then ignores.** `CdpPage` is bound to one attached
session, so a `target="_blank"` link opened a target the loop never saw: the next
snapshot read the unchanged opener until the repeat guard stopped the browse. An
init script neutralises `window.open` and rewrites `target` to `_self`, which is
simpler and more predictable than following targets - and the isolated context
disposes anything that escapes anyway.

**Wait for ever on a browser that went quiet.** Every CDP command has a 30-second
bound. `max_steps` cannot help: it counts iterations that *finished*, so one hung
`Runtime.evaluate` held the agent's turn and the panel open for as long as the run
was allowed to live.

**Report a page's own exception as a mystery.** A script that raised came back as
`{"className": "ReferenceError"}` and the parser said "the collector did not run"
- true, and no help in finding out why. `exceptionDetails` is read and the page's
own message quoted. This one was found by making the mistake: a refactor dropped
`pathOf` from the collector and the only symptom was that sentence.

**Trust the coordinates a snapshot recorded.** It did, and that was wrong. The
decision model answers *after* the snapshot, which on a page that re-renders is
long enough for everything to move - so a click on the stale centre lands on
whatever slid into that position, which is an action on an element that was never
in the candidate table and the bounded-action property gone. Every element now
carries a selector, and every action resolves it again, checks that what it found
still describes itself the way the table said it did, and uses the fresh
coordinates. An element that moved or changed is one step refused with a reason
the model reads, not the browse's end.

**Let the operation and the target contradict each other.** They are two
independent answers, so `TYPE_TEXT` aimed at a link is a pair the model can
produce - and typing starts by focusing, which for a link means *following* it.
The action would have happened and only then failed. Roles are checked before
dispatch: `TYPE_TEXT` needs a field that holds text, `SELECT` needs a dropdown.

**Read the accessibility tree.** It is the richer source and it is also the one the
page writes: `aria-label` is an author's sentence. A bounding rectangle that is on
screen, non-zero and not disabled is a fact about what a person could press.

## A dropdown is a value, not a click

Clicking a native `<select>` opens Chromium's own popup, whose options are not in
the DOM at all - so the next snapshot shows the same untouched dropdown, and a
form that needs one choice loops until the repeat guard stops it. `SELECT` is
therefore answered with a *value*, the way `TYPE_TEXT` is: the option is matched
on its visible label, set on the element, and `input` and `change` are dispatched,
which is what the listeners on that form are waiting for.

The options travel on the element rather than as choosable rows of their own,
which is the obvious design and the wrong one: a country list is two hundred
options and would spend the whole candidate cap describing one field. So a
dropdown is one row, its choices are listed with it (bounded, with a count for
the rest), and an option it does not have is refused rather than typed somewhere.

## Two guards, because a bounded action space is not a bounded run

A page can offer a legitimate action for ever - the cookie banner that reappears,
the "load more" that loads nothing - and choosing it every time is the loop working
correctly all the way to its ceiling. So the same action in the same place three
times running ends the browse as `blocked` while there is still something useful to
say, and `min_confidence` lets an operator refuse to act on a pick the decision
model was not sure about. It defaults to 0 - act on every pick, report the score -
because a floor that silently blocks a first browse is worse than one an operator
turns on after reading a few.

"The same place" is the URL, the scroll position and the roles and labels of what
the page offers. Not the URL alone, which a wizard or a paginated table defeats -
`Next` at the same index on the same address three times, each click advancing the
flow. And **not** the field values or the page's text, both of which were in there
and had to come out: a value changes the moment it is typed, so typing the same
thing ten times read as ten different states, and the text of any page with an
autocomplete on it differs every step. Measured against a live Wikipedia, with the
text included, eight identical `TYPE_TEXT` steps ran to the ceiling unremarked.
What the narrower signature costs is bounded and stated: a page whose *labels*
churn is not caught by this guard, and `max_steps` is what stops it.

## The two model paths, and the one that has no price

The decision model runs once per step and the run's own language model runs once
per field typed. Neither passes the host agent's `BudgetGuard` - they go out
through `Agent`s this package builds - so both are wrapped in `MeteredModel` and
book against the run's ledger (agenticos#802).

**Tokens, though, are not cost.** `price_request` prices a response through
`genai-prices`, and a decision model the snapshot does not know prices as `None`.
So a browse appears in Activity with its usage and without its money, and a
dollar-denominated budget cap does not constrain it. What constrains a browse is
`max_steps`. This is stated here rather than discovered from a budget that never
moved.

## Where page content goes

Every step sends the page's URL, its title and its element labels to the decision
model. On the vendor's public endpoint that is a third party, in a product sold as
self-hosted, and it may be the contents of a customer's internal system.

A bounded excerpt of the page's visible text goes with it, because without it the
engine cannot tell that it has finished - a price, a confirmation and "no results"
are text rather than controls, so `DONE` would be a guess. A value the agent
*types* does not: the history line the next decision reads says `filled textbox:
Password`, never what was in it, so a credential the host model wrote into a form
does not travel to a separately configured endpoint.

`decision_base_url` has an allowlist of its own -
`DECISION_MODEL_ALLOWED_HOSTS`, empty by default, which permits only the vendor's
endpoint. It needs one for a reason worth stating: the field is in the spec, and
the vault key is unsealed into a request header to whatever it names - so an
author who may *bind* a shared TypeSafe key, without the API ever returning its
value to them, could point it at a server of their own and read it out of the
header. Approval does not help, because the same author publishes the binding.

Two things make the destination a decision rather than an accident. The capability
requires an API key from this deployment's vault, so it cannot run until an operator
deliberately adds one - there is no ambient `TYPESAFE_API_KEY` path, and the key
follows the agent rather than the process. And `decision_base_url` points the
decision model somewhere else, for a deployment that has a private endpoint.
`docs/data-protection.md` says the same thing where an operator will look for it.

## The picker over a catalog, and the string underneath it

`decision_model` is offered from `app/core/catalog/decision_models.json` and
stored as a plain string. Both halves are deliberate. A moving alias is the right
answer for almost every agent and typing one is a chance to typo, so the Builder
shows a select; and a *pinned* build (`jev-1.13.0`) is the right answer for an
agent whose confidence floor was tuned against one, which TypeSafe accepts and
which a `Literal` would have forbidden. Nobody should wait for a release of this
platform to use a release of that one.

`decision_base_url` names its own default in the field description rather than
leaving it implicit in the SDK. Empty is the setting with the largest consequence
in this capability - it is the difference between page content staying inside a
deployment and leaving it - and a default destination nobody can see is a default
nobody audits.

## The live preview

`preview` sends the viewport to the chat as a JPEG per step, on the same channel
as a delegation's frames (`app/agents/browser_events.py`) - except that this sink
*answers*, which the delegation and compaction sinks do not. A detached turn
carries on by design, so a browse whose reader closed the tab would go on
capturing and base64-encoding a picture per step for nobody. The first
undelivered frame stops the screenshots; the narration keeps being offered,
because a few hundred bytes is not the cost worth avoiding and the socket may be
a channel rather than a browser tab. The console draws it as
a thumbnail card in the transcript and expands it into a resizable panel when
somebody asks - a panel that opened itself would say watching the browser matters
more than reading the answer, which is true for about four seconds. It is bounded by
`preview_width` without resizing anything, because the viewport *is*
`preview_width`: one number decides how wide the page renders and how wide the
picture is, which is also what keeps the frame a person watches identical to the
page the model was shown. It is a separate frame
from the step's narration so that encoding a picture never holds up the sentence,
and so a deployment that cannot afford the bandwidth turns the pictures off and
keeps the narration. A surface with no `browser_events` sink runs the browse
unnarrated, exactly as a delegation runs unnarrated on a surface that cannot show
one.
