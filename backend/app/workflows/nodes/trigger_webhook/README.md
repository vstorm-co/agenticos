# trigger.webhook

A workflow a signed HTTP delivery starts. Publishing a version that starts here
gives the workflow its own address and a signing secret, shown once; publishing
again keeps both.

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `out` | output | `WebhookTriggerOutput` | `body` (the delivery's JSON object), `delivery_id` |

The sender signs the exact body with HMAC-SHA256 and names each delivery; a
retry that repeats the id is answered with the first run and starts nothing.
The run acts as the member who published, checked afresh on every delivery.
