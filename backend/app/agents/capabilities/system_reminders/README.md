# System reminders

Re-states steering guidance mid-run to counter instruction fade: after many
tool-use turns a model progressively ignores the guidance it was given at the
start, and a single start-of-session prompt is not enough for extended work. This
capability re-injects targeted guidance on a cadence - a fixed line, the original
request re-stated, or a model-written nudge - and contributes no tools.

The strategy is a port of `pydantic-ai-harness`'s `SystemReminders`. Two things
this platform had to add to it are the whole of why it is not a thin wrapper.

## Why the cadence is durable

The harness keeps its request counter and per-reminder fire counts in memory and
resets them for each run, keyed by `id(reminder)`. On this platform a run is one
turn, and a conversation is rebuilt from the transcript every turn, so an
in-memory counter resets to zero each turn - and a reminder set to fire "every ten
requests" would never fire in a chat of ten one-request turns.

So the counter and the fire counts live in a `ReminderState` seeded from the
conversation's `reminder_state` column before the run and written back after it,
keyed by a stable string (a static reminder's position, or the name
`goal_reanchor` / `llm`) rather than an object id. Leaving and reloading a
conversation resumes the cadence rather than restarting it. The reminder *text* is
never stored - only the counters are.

## Why injection is cache-safe

A fired reminder is appended to the *tail* of the request as an ephemeral
`UserPromptPart` behind a `CachePoint`, inside `wrap_model_request` - which runs
after core has persisted the durable history. So the reminder reaches the model
but never enters `message_history`: no stale reminders pile up across turns, and
the cached prefix (tools, system, the real conversation) stays byte-identical turn
over turn while only the small reminder falls outside the cache. Injecting into
the system prompt instead would bust the cached prefix on every fire *and* pile up
stale reminders in history.

A leading `CachePoint` is added only when the request already carries a
user-content block for it to attach to; Anthropic and Bedrock reject one that is
the first content of a user message.

## The three reminder kinds

| Kind | Cost | Text it injects |
|---|---|---|
| `reminders[]` | none | A fixed line you write |
| `goal_reanchor` | none | The run's first user request, re-stated as the anchor |
| `llm_reminder` | one model call per fire | A short nudge a model writes from the recent transcript |

Each carries its own cadence: `interval` and `first_after` count model requests
across the whole conversation, and `max_fires` caps the total over its life. At
least one kind must be set, or the capability contributes nothing and is dropped
from the run - which is what a spec with an empty config means.

## Why the LLM reminder inherits the run's model

`llm_reminder` writes its text through an `Agent` it builds itself, so that request
never passes the budget guard - the guard is a capability on *our* agent, not on
the one the reminder builds. Its tokens are booked against the run's ledger through
`record_ambient_usage`, the way a compaction summary is, and it runs under the
run's usage limits minus one reserved request so it can never push the run past its
own `request_limit`. On any error - a provider failure, an exhausted reserved
budget, an empty answer - it falls back to the goal-reanchor line, so a failed
generation never blocks the run.

It inherits `ctx.model` rather than taking a model name from config on purpose: the
run's model is the one whose credential the vault resolved, and a model named as a
string would be looked up against process environment variables, which on this
platform is either nothing or somebody else's key. This is the same decision the
compaction capability makes about its summarizer.

## What this deliberately does not do

- **Arbitrary trigger callables.** The harness `Reminder` takes a
  `(RunContext) -> bool` predicate and `SystemReminders` takes arbitrary dynamic
  callables. Neither can be stored in a spec or exported as YAML, which is the
  contract every capability here obeys, so the dynamic seam is the two declarative
  producers above rather than a code hook.
- **Persist reminder text.** Only the cadence counters are durable. The text is
  regenerated or re-stated each turn and never enters the transcript.
