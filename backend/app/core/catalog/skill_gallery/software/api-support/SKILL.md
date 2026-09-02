---
name: API support
description: Answer integration questions with a request that works, and diagnose from status codes.
category: engineering
---

# Supporting an API integrator

Answer with something they can paste. A description of the request is half an
answer.

## Every answer includes

The method and path · required headers, named individually · a complete example
body · the shape of the success response · what a refusal looks like.

## Diagnose from the code

**401** — missing or expired credential. **403** — authenticated, not permitted;
name the permission. **404** on something that exists — usually the wrong tenant
context rather than a missing row, and that distinction saves hours.
**422** — read `details.fields`, it names the field. **429** — the limit and the
window.

## Ask for three things

The full request with secrets redacted, the complete response including headers,
and the timestamp. Without those, every diagnosis is a guess.

## Never

Tell somebody to retry without saying what changed, or blame their client
before checking the request that was actually sent.
