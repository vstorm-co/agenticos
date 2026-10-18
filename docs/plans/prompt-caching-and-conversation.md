# Provider-neutral prompt caching, and whether to adopt `Conversation`

Working notes for #2169, against Pydantic AI 2.55.0 (the version the lock pins).

## Caching: done in the same change

`PROMPT_CACHE_DEFAULTS` asked Anthropic and OpenRouter for their own cache flags
and nothing else. It is replaced by `PROMPT_CACHE = {"cache": True}` in
`app/agents/model_resolver.py`, merged under every profile's settings in the
factory as before.

What the neutral setting changes, by provider (Pydantic AI's own table):

| Provider | Before | Now |
|---|---|---|
| Anthropic | instructions, tools, last message | the same, through `anthropic_cache` (automatic caching for the conversation) |
| OpenRouter (Anthropic, Gemini models) | instructions, tools, last message | the same |
| Bedrock (Anthropic, Nova models) | nothing | instructions, tools, conversation |
| OpenAI (GPT-5.6 and later) | implicit only | explicit breakpoints as well |
| Google, Groq, Mistral, others | implicit or nothing | unchanged; the setting is ignored |

A profile opts out with `cache: false`, or caches only the prefix with
`{"messages": false}`. A profile written against the old flags keeps working:
a provider-specific flag overrides the neutral setting for that request. One
consequence worth knowing: a profile that sets only `anthropic_cache_messages:
false` turns off the neutral setting entirely, instructions and tools included,
which is Pydantic AI's rule rather than ours.

The OpenRouter profile's `openrouter_supports_cache_ttl=False` still applies: the
neutral setting asks for the provider's default retention, so no `ttl` is sent,
and Bedrock behind OpenRouter keeps accepting the request.

## System reminders keep their `CachePoint`

`SystemReminders` appends a reminder to the request tail behind its own
`CachePoint`. As Pydantic AI documents the neutral setting, that breakpoint is
still doing work: the library's conversation breakpoint goes at the end of the
request, which is the reminder itself, and the next request (which carries no
reminder) would miss that block. Read from the library's documentation, not
measured on a live provider. The explicit point marks the prefix *before* the reminder, so the
next request reads it from cache. When a request exceeds a provider's breakpoint
limit, Pydantic AI drops the oldest message breakpoints first, so the newest one -
this one - survives. Kept, unchanged.

## Observability and price

- `pydantic_ai.cache.*` spans come from Pydantic AI's own instrumentation, which
  `instrument_pydantic_ai()` turns on; they reach Logfire with every other run
  span. Not checked against a live Logfire project in this change.
- Cache reads and writes are priced from the request's own split
  (`price_request`), and #2170 checked the bundled `genai-prices` rates against
  Anthropic's list: Sonnet and Opus 5.5 reads at 0.05x input, writes at 1.25x.
  A run whose cache does not hit is priced exactly as before: the same input
  tokens at the input rate.

## `Conversation`: not adopted now

`pydantic_ai.Conversation` carries `messages`, a running `usage`, a
`conversation_id` and the `deferred_tool_requests` a paused run waits on, and is
passed back as `conversation=`. What it could replace here:

| Ours | `Conversation` | Verdict |
|---|---|---|
| History rebuilt from `messages` each turn (`ConversationService.model_history`), with the stored summary standing in for older turns, attachments re-attached, and other members' turns attributed | `messages` | Not a fit. Our history is assembled per person and per turn from rows other surfaces also write; a serialized message list would be a second copy to keep in step with the transcript |
| Per-run `UsageLimits(request_limit=max_steps)` | session-wide `usage` | No current need. Spend is bounded by money (budgets, per run and per month), not by a token count per session |
| `PausedRunState` for parked approvals and questions | `deferred_tool_requests` | Not a fit yet. `PausedRunState` also carries the delegation tree, each delegate's spend and its place, and the plan - none of which `Conversation` holds |
| Our conversation UUID | `conversation_id` | Worth doing: passing our id would correlate a thread's runs in Logfire and on `ModelResponse.conversation_id`. Small, and independent of the rest |

Proposed follow-up, not filed: pass the platform's conversation id as Pydantic
AI's `conversation_id` on every run, so a thread's runs share one id in traces.
Nothing else is worth moving until a session-wide limit or a resumable
`Conversation` covers what `PausedRunState` carries.
