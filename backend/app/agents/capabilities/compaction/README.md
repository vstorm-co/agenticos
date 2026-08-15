# Compaction

Keeps a run's message history inside the model's context window. Contributes no
tools: it rewrites what a request carries, and there is nothing in that for a
person to approve.

The strategies come from
[`pydantic-ai-harness`](https://github.com/pydantic/pydantic-ai-harness). This
package is the two things a platform has to add to them.

## What it reaches, and what it does not

**One run.** Between turns the history is rebuilt from the transcript by
`app.services.agent.build_message_history`, which reconstructs a conversation as
user and assistant *text* and drops tool calls, tool returns and thinking. No
edit made here survives a turn boundary.

That is not the limitation it sounds like. The history worth compacting is the
hundred-step tool loop `DEFAULT_MAX_STEPS` allows, where a single directory
listing or knowledge search is tens of thousands of tokens; a conversation's
turns are text and are small. It does mean a summary is paid for once per run
rather than amortised across a thread, which is why the default strategy spends
the cheap passes first.

## The strategies

| `strategy` | Cost | What it does |
|---|---|---|
| `tiered` *(default)* | escalates | Clears old tool results; summarises only if still over target |
| `clear_tool_results` | zero-LLM | Blanks the content of old tool results, keeping the last few pairs |
| `sliding_window` | zero-LLM | Drops the oldest whole messages down to a tail |
| `summarize` | one model call | Summarises older messages, keeping the recent tail |

`tiered` is the default because summarising turns input tokens into output
tokens, which are billed at a premium and generated serially. A tool result that
has already been acted on is dead weight, and clearing it costs a cache write.

## Configuration

| Field | Default | What it is |
|---|---|---|
| `strategy` | `tiered` | Which of the four above |
| `max_fraction` | `0.8` | Fraction of the window at which compaction starts |
| `keep_messages` | `20` | Recent messages that survive a summary or a window |
| `keep_tool_pairs` | `3` | Recent tool calls that keep their results |
| `context_window` | *(unset)* | Override the window in tokens |
| `fallback_context_window` | `200000` | Window to assume when the model's cannot be resolved |

Flat scalars and one enum, deliberately: the Builder generates this form from
`config_json_schema` and renders string, number, boolean and enum fields. A
nested list of tiers would arrive as a text box, so the tiers are chosen by
`strategy` rather than composed by the author.

There is no field naming a cheaper model to summarise with. The summary inherits
the run's model because that is the one whose credential was resolved from the
vault; a model named here as a string would be looked up against process
environment variables, which on this platform is either nothing or somebody
else's key.

### Why a fraction, and when the fraction is wrong

An absolute token trigger is only correct for the model it was measured against.
The same agent here runs on whichever profile its spec points at, so the trigger
is a fraction resolved per request against the model's real window.

Resolution fails, or is wrong, in two ways that matter here — both in the
direction that breaks a run rather than the one that wastes a summary:

- **A spec with fallbacks builds a `FallbackModel`**, whose `model_id` is a
  composite `fallback:...` that resolves to nothing. The fraction is then taken
  of `fallback_context_window`.
- **`genai-prices` records 1,000,000 for `anthropic:claude-sonnet-4-5` against a
  real 200,000.** `max_fraction=0.9` there resolves to a 900,000-token trigger,
  compaction never fires, and the provider refuses the request instead.

The window is taken from the model profile, which recorded it from the provider's
own listing when somebody added the model (#773). Where the profile recorded
nothing — an older row, a curated list, a listing that could not be reached — the
strategy resolves the window itself and the two cases above apply.
`context_window` on the binding overrides both, for a deployment that knows better
than the provider: what a listing publishes is the maximum a model *can* be made
to accept, and a beta- or tier-gated one gets less.

## Metering

`SummarizingCompaction` writes its summary through an `Agent` it constructs
itself, so that request never passes `BudgetGuard.wrap_model_request` — the guard
is a capability on *our* agent, not on the one the strategy builds. Its tokens
land in `ctx.usage` and would land nowhere else: the run under-reports its cost
and no cap can stop a compaction loop. That is #16 wearing a different hat.

`MeteredCompaction` wraps every strategy, measures `ctx.usage` across the hook
and books the difference through `record_ambient_usage`, which the runner's
`metered_by(built.ledger)` block routes to the run's ledger.

It wraps the zero-LLM strategies too. An allowlist of "these can spend" is a list
somebody has to remember to add to, and the entry they forget is a model call
nobody is billed for — the same omission the wrapper exists to close.

What it cannot do is *stop* the spend. `BudgetGuard` refuses in
`wrap_model_request`, which runs after this hook, so a compaction that crosses a
cap is recorded here and refused on the request after it.

## What this deliberately does not do

Compact across turns, or expose a context gauge. The first needs a history that
survives a turn, which is a change to how conversations are replayed rather than
a capability setting. The second is `ReportContextUsage` and belongs next to the
cost line in the chat, not in a spec.
