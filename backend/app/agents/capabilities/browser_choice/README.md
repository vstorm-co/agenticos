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
offers, so the capability is `side_effecting` on both the capability and the tool,
and an approval gate is what stands between an injected page and an unattended
press. The action space is bounded, not harmless.

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
image. `cdp_url` points at a browser service an operator runs and isolates, and
the endpoint is SSRF-checked at publish, off the event loop, by `validate_cdp_url`
- `browser_use`'s arrangement (agenticos#33). A browser in the application
container widens the surface the platform itself runs on, for nothing.

**Rank the candidate set.** Truncation to `candidate_cap` is by document order and
nothing else. Scoring the elements by relevance to the goal would put the decision
this capability exists to make back inside an opaque function, and would make two
runs over one page offer different tables. The loop's answer to a page too dense
for the cap is to scroll.

**Re-resolve an index at action time.** The coordinates a click uses come from the
snapshot that offered the element. A page that re-rendered in between has
renumbered everything, and pressing "element 7" after that presses whatever moved
into seventh place.

**Read the accessibility tree.** It is the richer source and it is also the one the
page writes: `aria-label` is an author's sentence. A bounding rectangle that is on
screen, non-zero and not disabled is a fact about what a person could press.

## Two guards, because a bounded action space is not a bounded run

A page can offer a legitimate action for ever - the cookie banner that reappears,
the "load more" that loads nothing - and choosing it every time is the loop working
correctly all the way to its ceiling. So the same action on the same page three
times running ends the browse as `blocked` while there is still something useful to
say, and `min_confidence` lets an operator refuse to act on a pick the decision
model was not sure about. It defaults to 0 - act on every pick, report the score -
because a floor that silently blocks a first browse is worse than one an operator
turns on after reading a few.

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

Two things make that a decision rather than an accident. The capability requires an
API key from this deployment's vault, so it cannot run until an operator
deliberately adds one - there is no ambient `TYPESAFE_API_KEY` path, and the key
follows the agent rather than the process. And `decision_base_url` points the
decision model somewhere else, for a deployment that has a private endpoint.
`docs/data-protection.md` says the same thing where an operator will look for it.

## The live preview

`preview` sends the viewport to the chat as a JPEG per step, on the same channel
as a delegation's frames (`app/agents/browser_events.py`). It is a separate frame
from the step's narration so that encoding a picture never holds up the sentence,
and so a deployment that cannot afford the bandwidth turns the pictures off and
keeps the narration. A surface with no `browser_events` sink runs the browse
unnarrated, exactly as a delegation runs unnarrated on a surface that cannot show
one.
