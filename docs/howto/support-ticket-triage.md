---
title: "Triage incoming support requests from your own app"
description: "Fire an agent from your own backend with a signed webhook, and have it classify, draft a reply and flag security reports."
---

# Triage incoming support requests from your own app

Wire your own support form or ticketing system to an agent with an
[event trigger](../triggers.md) on the **API** source — the generic `webhook`
source that fires on any signed JSON delivery. Three synthetic tickets, one of
them a security report, check that classification, drafting and the security
flag all work before you point a real system at it. This is a procedure to run,
with one recorded run as a reference.

## What you need

A [running installation](../install.md) with a model profile. No sandbox, no
embedding model and no external account — the API source signs its own
deliveries, so there is no provider console to configure.

## Prepare the input

Three tickets, as your own backend would send them — the whole JSON body reaches
the agent's prompt, so any shape works as long as you write the instructions
around it:

```json
{"ticket_id":"T-1001","from":"lena@acme-example.com","subject":"Charged twice this month","body":"I was billed 49 USD twice on the 3rd for the same Pro plan invoice. Can you refund the duplicate?"}
{"ticket_id":"T-1002","from":"marek@example.org","subject":"Export button does nothing","body":"Clicking Export CSV on the reports page just spins forever and nothing downloads. Chrome, latest version."}
{"ticket_id":"T-1003","from":"researcher@example.net","subject":"Found an issue with account access","body":"By changing the id in the /api/v1/invoices/{id} URL I was able to view another customer's invoice PDF without being logged in as them. Tested with three different ids, all worked."}
```

Reference: T-1001 is billing, medium priority. T-1002 is technical, medium
priority. T-1003 describes an IDOR — it should come back security, urgent, with
an explicit flag.

## Build the agent

1. Create an agent in **Agents → New agent** and select your model profile. No
   capability is required for this trial.
2. Set the instructions below, then **Publish**.

```text
You triage inbound support tickets for a small SaaS product.
Be concise and factual. Never invent facts not in the ticket.
```

3. Open **Routines → New event trigger**, choose the agent and the **API**
   source. Set the trigger's own prompt — this is what is sent ahead of the
   delivery, every time it fires:

```text
A support ticket just arrived as JSON below. Classify it by category (billing,
technical, account, security, other) and priority (low, medium, high, urgent).
Draft a reply the support team can send. If the ticket describes a possible
security vulnerability or exposure of somebody else's data, say so explicitly in
a line starting with 'SECURITY:' and set priority to urgent.
```

4. Save. Copy the **webhook URL** and the **signing secret** it shows you once —
   the API source is `manual` delivery, so nothing registers itself and you
   choose the secret yourself. [Triggers](../triggers.md#the-mechanism-once)
   covers what the two mean.

## Run it

Sign each ticket's exact bytes with the trigger's secret and POST it. See
[signing a delivery yourself](../triggers.md#signing-a-delivery-yourself) for the
two footguns — do not re-serialize the body, and sign only the bytes you send:

```bash
SECRET='your-signing-secret'
URL='http://localhost:8110/api/v1/webhooks/triggers/webhook/<trigger_id>'
BODY='{"ticket_id":"T-1001","from":"lena@acme-example.com","subject":"Charged twice this month","body":"I was billed 49 USD twice on the 3rd for the same Pro plan invoice. Can you refund the duplicate?"}'

SIG="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | sed 's/^.* //')"

curl -sS -X POST "$URL" \
  -H 'Content-Type: application/json' \
  -H "X-Signature-256: $SIG" \
  --data-raw "$BODY"
```

Repeat for T-1002 and T-1003. Each accepted delivery answers `202` — accepted, not
finished. Read the fired runs in **Activity**, or under the trigger's own
conversation in **Routines**.

## Check the result

| Check | Reference |
| --- | --- |
| T-1001 | Category billing, priority medium, a reply that acknowledges the duplicate charge |
| T-1002 | Category technical, priority medium, a reply that asks for reproduction details |
| T-1003 | Category security, priority urgent, a line starting `SECURITY:` naming the exposure |
| The `202` response | Arrives immediately; the run itself finishes seconds later, asynchronously |
| An unsigned delivery of the same body | `403`, refused before the agent runs at all |
| A delivery with the body re-serialized by your HTTP client instead of sent raw | `403` — the signature no longer matches the bytes actually sent |

!!! example "Recorded on v0.0.504, 25 September 2026"

    Model: Claude Sonnet 4.6 through OpenRouter. All three deliveries answered
    `202` and completed within about 6 seconds each, recorded with surface
    `schedule` — event-trigger fires share that surface with scheduled ones.

    T-1001: *"Category: Billing, Priority: Medium"*, a reply asking for the
    invoice ID to process a refund. T-1002: *"Category: Technical, Priority:
    Medium"*, a reply requesting browser console output. T-1003: *"Category:
    Security, Priority: Urgent"*, followed by `SECURITY: Reporter claims
    unauthenticated/unauthorized access to other customers' invoice PDFs via
    IDOR (Insecure Direct Object Reference) on /api/v1/invoices/{id}. Multiple
    accounts confirmed affected."` — and a draft reply asking the reporter not to
    test further while it is investigated. Combined cost for the three runs:
    0.013 USD.

    Both refusal paths were checked too: the same body sent with no
    `X-Signature-256` header answered `403`; and a body signed as a string but
    then sent through a client's own `json=` re-encoding — same content,
    different bytes — also answered `403 AUTHORIZATION_ERROR: Webhook signature
    did not verify`, confirming the signature covers the exact bytes on the
    wire rather than the JSON's logical content.

## When it goes wrong

- **Every delivery comes back `403`.** The signature covers the *exact* bytes
  sent. `echo` adds a trailing newline that may or may not match what was signed;
  use `printf '%s'` and `curl --data-raw`, and never let a client re-encode a
  dict after you signed the string.
- **`202` but no run appears.** That means accepted, not finished — a
  Prefect flow runs it in the worker. Give it a few seconds and check Activity,
  filtered to the agent.
- **The security flag did not fire.** The flag is instructions, not a built-in
  classifier — reread the trigger's prompt and tighten what counts as a security
  report if a synthetic case like T-1003 is missed.
- **You only need to test the prompt, not the delivery path.** Use **Run now** on
  the trigger first — it fires the agent's base prompt with no delivery context,
  no signature and no webhook involved, which will not exercise classification
  since there is no ticket JSON to classify, but confirms the agent, its budget
  and its publish state all work.
- **Zapier or Make instead of a script.** Neither has a built-in HMAC action;
  budget an hour for a code step that signs the body, not five minutes of
  clicking. See [triggers](../triggers.md#zapier-and-make-cannot-do-this-without-a-code-step).

## Record the trial

Keep the three ticket bodies, the trigger's prompt, the signing secret's origin
(not its value), each delivery's HTTP status, and the run each one produced in
Activity. A person still reads every draft before it goes out, and decides
whether the security flag threshold is tight enough for a real inbox before
pointing a live ticketing system at this webhook.

## Next steps

The same API source works for anything else that can sign and POST JSON — a
form submission, a marketplace listing change, a monitoring alert. For a mailbox
instead of your own app's tickets, see
[triage your inbox and draft replies](email-triage.md), which uses the Gmail
source instead of a signed delivery.
