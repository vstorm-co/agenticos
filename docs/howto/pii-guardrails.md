---
title: "Keep personal data out of an agent's prompts and answers"
description: "Configure the guardrails capability to redact emails, phone numbers, card numbers and secrets, then check what the model actually received against what the visitor saw."
---

# Keep personal data out of an agent's prompts and answers

Turn on the [guardrails capability](../reference/capabilities.md#guardrails) on a
small test agent and send it synthetic personal data. The result to look for is
two different pieces of text: what the run's transcript shows for the model, and
what the run actually paid the provider to read. This is a procedure to run, with
one recorded run as a reference.

## What you need

A [running installation](../install.md) with a model profile. No sandbox and no
embedding model are needed. The capability adds no tools, so nothing beyond
**Guardrails** in the Toolbox is required.

## Prepare the input

No file this time — the input is the chat message itself. Use this line, which
carries one of each kind of personal data the capability recognises:

```text
My email is jane.doe@example.com, my card number is 4111 1111 1111 1111,
my SSN is 123-45-6789, and my phone number is 415-555-0132.
```

The reference facts: `redact_pii_*` scrubs email, IBAN, credit card
(Luhn-checked), US SSN and phone number. A phone number is checked against the
numbering plan of its country: one written with `+` is caught for any country, a
national one such as `415-555-0132` only for the countries in **phone_regions**,
which defaults to `US, GB, DE, PL`.

## Build the agent

1. Create an agent in **Agents → New agent** and select your model profile.
2. In **Toolbox**, enable **Guardrails**. It contributes no tool — there is
   nothing here for a person to approve, only a check on text.
3. Under the capability's config, turn on **Redact API keys and tokens from the
   user's prompt**, **Redact emails, phone numbers, IBANs, cards and SSNs from
   the prompt**, **Redact API keys and tokens from the agent's answer** and
   **Redact emails, phone numbers, IBANs, cards and SSNs from the answer**. Leave
   **phone_regions** at its default, which includes `US`. Set **Block the run if the prompt
   contains any of these terms (comma or newline separated)** to `wire transfer`.
4. Set the instructions below, then **Publish**.

```text
You are a signup-support assistant.
When the user gives you account details, confirm receipt by repeating them back in a bulleted list.
End every answer with a new line reading exactly: Reference key: sk-live-51ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789
```

Asking the agent to repeat the details back is what gives the input edge
something to show: whatever reaches the model redacted can only be repeated
redacted. The fixed reference key is there so the output edge has something
deterministic to catch, since forcing a model to invent its own secret is not
reliable.

## Run it

Send the fixture message in a fresh test conversation, then send a second,
unrelated message:

```text
I need to send a wire transfer today, can you help?
```

## Check the result

| Check | Reference |
| --- | --- |
| The reply | Does not repeat the email, card number, SSN or phone number in the clear |
| Phone number in the reply | Absent, or quoted back as `[redacted:phone]` |
| `Reference key:` line in the reply | Reads `Reference key: [redacted:openai_key]`, not the real value |
| The run's transcript (Activity) for the user's own turn | Shows the original, unredacted message you typed, phone number and all |
| The wire-transfer message | The run's status is `guardrail_blocked`, cost `0`, and no answer is produced |
| The same wire-transfer message with the keyword unset | Runs normally — the block is the keyword, not the topic |

The second row of the table is the one worth sitting with: the phone number is
national, so it is caught only because `US` is in **phone_regions** — take `US`
out and it reaches the model exactly as typed. The fourth row is the other one — a person reviewing
Activity to see "what happened" sees the visitor's real input, because the
guardrail rewrites what the *model* reads, never the stored conversation turn.

!!! example "Recorded on v0.0.504, 25 September 2026, before phone redaction"

    Model: Claude Sonnet 4.6 through OpenRouter. First reply: *"some of your
    details were automatically redacted for your security before they reached
    me, so I was not able to see your email, card number, or SSN"*, followed by
    `Phone Number: 415-555-0132` quoted back unchanged and `Reference key:
    [redacted:openai_key]`. Cost 0.003 USD. That run predates the phone
    detector ([#1901](https://github.com/vstorm-co/agenticos/issues/1901));
    with it, the number reaches the model as `[redacted:phone]`.

    The run's transcript stored the user turn as
    `My email is jane.doe@example.com, my card number is 4111 1111 1111 1111,
    my SSN is 123-45-6789, and my phone number is 415-555-0132.` — the full,
    original text, unredacted — while the stored assistant turn already carried
    `[redacted:openai_key]`.

    One more thing showed up only on the wire: the WebSocket's `text_delta`
    frames streamed the real reference key, character by character, before
    the `final_result` frame replaced the whole answer with the redacted
    version. Redaction runs on the finished answer, not on each streamed token —
    `widget.js` overwrites its rendered text with `final_result.output` for
    exactly this reason, but a client that only appends deltas would show the
    secret for the second or two before the swap.

    The wire-transfer message: `error` — *"This request was blocked by an input
    guardrail."* — with no `complete` frame after it. The run recorded status
    `guardrail_blocked`, `0` input and output tokens, cost `0.000000`.

## When it goes wrong

- **A value you expected redacted comes through untouched.** Check it against the
  five detectors: email, IBAN, credit card (checksum-verified), US SSN and phone
  number. A national phone number needs its country in **phone_regions**, and a
  number that is not valid in its country's numbering plan is left alone. A
  physical address or a name are not covered — this is a pattern layer, not a
  model that understands what personal data is.
- **A streaming client shows a secret for a moment.** Output redaction runs on
  the finished answer, after the `text_delta` frames have gone out. Render the
  `final_result` text, as `widget.js` does, rather than only appending deltas.
  Buffering the answer when output screening is on is tracked in
  [#1900](https://github.com/vstorm-co/agenticos/issues/1900).
- **The block did not fire.** `blocked_keywords_*` matches a literal, case-insensitive
  substring. A block also needs the edge's own toggle — a keyword list on the
  output edge does nothing to the input.
- **The transcript still shows the raw value.** That is expected on the input
  edge: only what reaches the model is rewritten, not the stored turn a person
  reviews later. Redact before storage is a different feature this one is not.
- **A run shows `guardrail_blocked` you did not intend.** Read the run's `error`
  field — it names the edge (`input`, `output` or `tool_result`) but never the
  matched text, by design, so check the keyword list itself.
- **Tool-result screening seems unused.** It only matters once an agent has a
  tool that reads untrusted content — a fetched page, a file, an MCP response.
  This trial has none, so that edge was configured but never exercised.

## Record the trial

Keep the exact message, the agent version, which edges and keywords were
configured, the run's transcript for both turns, and the run's `status` and cost
from Activity. A person decides whether these five detectors are enough for a
given agent, which countries belong in its **phone_regions**, and whether tool-result screening
belongs on before any tool that reads the outside world is added.

## Next steps

The [guardrails reference](../reference/capabilities.md#guardrails) lists the
exact patterns and the three edges in one table. If the agent will read anything
fetched from outside — a web page, an MCP server, an uploaded file — turn on the
tool-result edge before that capability goes live, not after.
