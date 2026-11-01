# webhook.respond

Answers the webhook delivery that started the run. A delivery to a graph holding
this step waits for the run instead of taking `202` on admission, and the first
respond step to complete names what its sender gets.

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; the body is bound |
| `out` | output | `WebhookResponse` | `status_code`, `headers`, `body` - the answer, handed on |

Config: `status_code` (200-599, default 200) and `headers`. The headers the API's
own response owns are refused at publish: framing, `Content-Type` (the body is
always JSON), `Set-Cookie`, and the CORS and browser-policy headers. The bindable
input is `body`, any JSON value.

## Once

The answer is recorded on the run in the transaction that completes the step,
and only if the run has not answered: a second respond step, or the same one in
a loop, answers nobody. The run goes on after it. A run no webhook started - a
test run from the editor, an API call - has nobody waiting, and the step only
records what it would have answered.

## Effect kind and retries

`effect_kind="pure"`, `retry_guarantee="idempotent"`. Answering is the door's
job, not the step's: the step writes a value the door reads.
