---
title: "Route requests to a team of specialist agents"
description: "Build a front-desk agent that delegates a billing or a technical question to a published specialist, and asks when a question is ambiguous."
---

# Route requests to a team of specialist agents

Build three agents: a billing specialist, a technical specialist, and a front
desk that routes a question to whichever one it belongs to - or asks, when it
is not clear. Each specialist is published separately, so it is reviewed,
versioned and can be reused by other front desks. This is a procedure to run,
with three recorded questions as a reference.

## What you need

- A [running installation](../install.md) with a model profile for all three
  agents.
- `agents:run` on both specialists, to pin them from the front desk - the same
  permission a channel mention or a delegation check anywhere else in the
  product resolves. See [permissions](../permissions.md#delegation-is-not-a-privilege-boundary).
- No knowledge collection, sandbox or MCP connection for this fixture.

## Prepare the input

A small synthetic product, so the specialists' facts are checkable:

**Billing facts** - Basic plan 9 USD/month, Pro 29 USD/month, both billed
monthly. A full refund within 14 days of a charge, no reason needed; none
after. Invoices are emailed on the charge date and always available from the
account's Billing page.

**Technical facts** - The API key lives under Settings → API keys;
regenerating one immediately revokes the old one. The rate limit is 60
requests per minute per key; a `429` names the seconds to wait. Status and
incident history are posted at a status page.

## Build the two specialists

Publish each one as its own agent, with no capabilities - each answers only
from the facts you gave it.

1. **uc-billing-specialist** - instructions: state the billing facts above, and
   say that a question outside them is not something this agent covers.
2. **uc-tech-specialist** - instructions: state the technical facts above, with
   the same refusal for anything else.

Publish both before building the front desk - a delegate must be a published
agent you may run, referenced by its slug.

## Build the front desk

1. Create a third agent, **uc-front-desk**, and select your model profile.
2. In **Toolbox**, enable **Delegation**. Leave `allow_dynamic` off - this
   agent only ever calls the two specialists you name, never one it invents.
3. Under **Delegates**, add both published specialists, pinned to their
   current version.
4. Set a budget and a step limit for the trial.
5. Set the instructions below, then **Publish**.

```text
You are the front desk for this product's support. You never answer a billing
or technical question yourself.
Route a billing question (pricing, refunds, invoices, charges) to the billing
specialist with task(description=..., subagent_type="uc-billing-specialist").
Route a technical question (the API, keys, rate limits, uptime) to the
technical specialist with task(description=..., subagent_type="uc-tech-specialist").
If a question could be either, or names neither, ask the user one short
question to tell which team it belongs to before delegating anything.
Relay the specialist's answer; do not add facts of your own.
```

`task` is not side-effecting, so neither delegation asks for approval by
default - the specialist's own tools are what a person would approve, on the
specialist's own spec.

## Who pays, and what the user sees

The front desk's run pays for the whole exchange: one shared spend ledger
covers the parent and every specialist it calls, and the front desk's budget is
the one enforced mid-conversation. Each specialist still gets its own row in
Activity, with `parent_run_id` set to the front desk's run - so "what did the
billing specialist cost this month" has an answer that does not double the
organization's bill. See
[what a delegated run is recorded as](../governance.md#what-a-delegated-run-is-recorded-as).

The person asking sees one continuous reply. The front desk relays what the
specialist said; nothing in the transcript looks like a handoff unless you open
the run in Activity and see the delegation underneath it.

## An approval inside a delegation

Neither specialist here has a gated tool, so nothing parks. If one did - a
`send_email` capability on the billing specialist, say - the approval would
still reach the same queue the front desk's own caller is watching, naming
**which delegate** proposed the call, not just the tool. Approving it resumes
that specialist from where it stopped, rather than delegating again from
scratch. See [an approval inside a delegation](../governance.md#an-approval-inside-a-delegation).

## Run it

Ask the front desk three questions, in separate conversations:

```text
I was charged twice this month, can I get a refund on the extra charge?
```

```text
My integration keeps getting 429s, what's the limit and where do I check status?
```

```text
Something changed and now it doesn't work like before.
```

## Check the result

| Check | Reference |
| --- | --- |
| Billing question | Delegates to `uc-billing-specialist`; the reply states the 14-day refund rule |
| Technical question | Delegates to `uc-tech-specialist`; the reply states the 60/minute limit and the status page |
| Ambiguous question | No delegation happens; the front desk asks which team it belongs to |
| Activity, billing run | A child run under the front desk's, `parent_run_id` set, its own cost |
| Activity, technical run | Same shape, under `uc-tech-specialist` |
| A question naming neither team and refusing to clarify | The front desk still asks rather than guessing which specialist to call |

!!! example "Recorded on v0.0.504, 25 September 2026"

    Model: Claude Sonnet 4.6 through OpenRouter, all three agents. The refund
    question produced one `task` call to `uc-billing-specialist`
    (cost 0.0236 USD for the front-desk run, including the delegate), whose
    reply named the 14-day window and pointed at the Billing page. The rate
    limit question produced one `task` call to `uc-tech-specialist`
    (0.0227 USD), whose reply named 60 requests per minute and the status page.
    The ambiguous message produced no delegation at all: "Could you tell me a
    bit more about what changed - is this related to billing... or something
    technical...?" (0.0066 USD). The billing specialist's own run row recorded
    0.0057 USD, a child of the front-desk run, confirming the shared-ledger,
    separate-row shape above.

## When it goes wrong

- **The front desk answers directly, no delegation.** The instructions were
  not followed, or `subagents` is not bound - check the Toolbox before
  rereading the prompt.
- **Publishing the front desk is refused, naming a delegate.** Either
  specialist is unpublished, or you may not run it - `agents:run` on that
  specialist's row is what pinning it checks.
- **The front desk always asks, even for a clear billing question.** The
  instructions' routing rule is too strict, or the model is reading "could be
  either" too broadly - narrow the examples in the prompt.
- **A specialist answers a question outside its facts instead of declining.**
  Its own instructions do not say to refuse; add the explicit refusal line
  used above.
- **A delegate's version moved without you asking.** It did not - a pin only
  moves when the front desk's spec is republished against the new version. See
  [a pinned delegate does not move on its own](../governance.md#a-pinned-delegate-does-not-move-on-its-own).

## Record the trial

Keep each question, which specialist answered, the reply, the child run in
Activity with its own cost, and the front desk's total. A person still decides
what counts as ambiguous enough to ask about, reviews each specialist's facts
before publishing it, and judges whether a relayed answer actually reflects
what the specialist said.

## Next steps

Add a third specialist and watch the front desk's routing instructions get
harder to keep unambiguous - a good sign that team is outgrowing hand-written
routing rules. `allow_questions` lets a specialist ask the same person the
front desk is talking to, mid-answer, instead of guessing; see
[delegation](../reference/capabilities.md#delegation).
