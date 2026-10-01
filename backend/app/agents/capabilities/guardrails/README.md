# Guardrails

An input/output/tool-result check that can **redact** content or **stop** a run.
This is the one capability that is governance rather than convenience: the
platform's value is "mostly in what it refuses", and a guardrail is that sentence
made executable.

## What it does

Three edges, each configured independently:

- **input** — the user's prompt, before the first model request.
- **output** — the agent's final answer.
- **tool result** — what a tool returned, before the model reads it. This is the
  only guard on untrusted content entering the loop: a fetched page, a file, an MCP
  server's response.

On each edge, two kinds of check, drawn from `pydantic-ai-harness`'s ready-made
detectors:

- **redact** secrets (API keys, tokens, JWTs, PEM blocks) and/or personal data
  (email, IBAN with mod-97, card with Luhn, US SSN, phone number). A match is
  rewritten in place and the run carries on — an agent that quoted a key back has
  still done the work.

- **block** on a keyword list. A match ends the run.

Phone matching lives in `app/core/phone.py`, shared with the ML PII service.
It uses libphonenumber (`phonenumberslite`) with strict grouping to avoid matching
IDs such as `ORD-2026-000417`. National formats use `phone_regions`; international
(`+`) formats work regardless of that list. Bare digits remain ambiguous:
`123456789` is a valid Polish landline, so listing PL also redacts that order ID.
The region setting is limited to 256 characters before splitting or normalizing,
so repeated codes and empty entries cannot cause unbounded parser allocations
when validating a stored draft.

Each region scans the whole text. `phone_limits` allows 200,000 characters and
10,000 digits for up to four regions, reducing both proportionally beyond four;
at the maximum 16 regions, the limits are 50,000 characters and 2,500 digits.
These bounds address both duplicate-match memory use and synchronous CPU work:
the original four-region measurements were about 0.7 seconds for digit-heavy
text at the digit limit or repeated full-width brackets at the character limit.
The matcher's rejected-candidate cutoff is disabled so it cannot silently skip
numbers near the end of a text.

Guardrails check raw length before any redaction, then length and digits after
the harness redactors, raising `GuardrailBlocked` on refusal. The ML endpoint
checks the original input against its character limit and the shared phone
limits, returning a field error. Neither passes an unchecked input to the matcher.

## Why a block *stops* the run

The harness makes a `block` graceful: an input block substitutes a refusal and the
run *completes* with it, a tool block replaces the result and the model continues.
Here a block instead raises `GuardrailBlocked`, which the runner maps to
`RunStatus.GUARDRAIL_BLOCKED` — its own status, beside `BUDGET_EXCEEDED`, because a
trip is the platform working and an operator filtering for problems should not wade
through it. A refusal that reads like a normal completed answer is not a refusal
anyone can find later.

Redaction keeps the harness semantics: `replace` rewrites and the run finishes.

## What it deliberately does not do

- **No `guard=<callable>`.** An agent is data, not code. The config selects and
  parameterises detectors; it cannot carry a Python function. A detector the config
  cannot express is a follow-up to the detector library, not a hole here.
- **No tool-argument screening.** The harness's text detectors adapt to the prompt,
  the output and a tool *result*; tool *arguments* are a structured mapping with no
  text adapter. Screening them needs a bespoke, non-shipped adapter — out of scope.
- **No `approve` verdict.** The harness tool guard can defer a call for human
  approval. AgenticOS already has that: the approval gate (`approval/`) parks a run
  at `AWAITING_APPROVAL` per tool. A second, rule-driven path to the same mechanism
  would be the thing this capability is here to avoid — two ways to do one thing,
  drifting. A guardrail here is automated; the human decision stays with the gate.
- **No model-calling detector.** Every detector shipped is a pure function, so an
  agent's budget is untouched and #16's ambient-spend metering is not engaged. A
  future detector that calls a model must book its spend through
  `record_ambient_usage`, the way `MeteredCompaction` does, before the guard can be
  trusted not to hide cost.

## Known edge

An **input** redaction on a **multimodal** prompt raises `UserError` in the harness
(substituting a scrubbed string would drop the attachments), which fails the run
rather than blocking it cleanly. Redaction is intended for text prompts; a
multimodal agent should not enable input redaction until the harness grows a
text-part-only rewrite.
