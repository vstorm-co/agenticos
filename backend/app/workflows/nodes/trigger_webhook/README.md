# trigger.webhook

A workflow an authenticated JSON event starts. With `source_id`, publishing
subscribes this entry to a reusable event source. The source owns its URL and
credentials; neither is copied into the workflow definition. Without `source_id`,
publishing gives the workflow its own address and a signing secret, shown once;
publishing again keeps both.

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `out` | output | `WebhookTriggerOutput` | `body` (the delivery's JSON object), `delivery_id` |

Dedicated senders sign the exact body with HMAC-SHA256 and name each delivery;
a retry that repeats the id is answered with the first run and starts nothing.
A reusable source authenticates once and durably queues each subscriber, then
acknowledges receipt. Its reachable branch cannot contain Respond to webhook;
dedicated endpoints keep their synchronous responses.

The run acts as the member who published, checked afresh on every delivery.
Queued source work keeps the published version and member captured at receipt,
and rechecks source-use and workflow-run access before admitting a run. Source
pause and this entry's pause are independent. Live source samples use the same
`{body, delivery_id}` shape for pinning, bindings and step tests; they never need
a payload transformation step or become a requirement for publishing.
