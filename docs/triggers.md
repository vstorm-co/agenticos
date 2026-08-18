# Setting up an event trigger

An **event trigger** fires an agent when a signed webhook arrives - a GitHub issue,
an inbound email, a LinkedIn post, or anything that can POST signed JSON.
[Concepts](concepts.md#trigger) covers what a trigger *is* and how a fired run behaves;
[Governance](governance.md) covers what it spends and how a refusal is handled. This
page is what you do next: how to point a real provider at the webhook, what the
delivery has to contain, and how to test the whole thing from a laptop.

If you only need the agent to run on the clock, you want a **schedule**, not an event
trigger - no webhook, no secret, no provider to configure. Everything below is for the
event case.

## The mechanism, once

An event trigger hands you two things: a **webhook URL** and a **signing secret**. A
provider POSTs its payload to the URL and signs the request; the platform recomputes
the signature and fires the agent only if the two match.

- **The URL** is built on the deployment's one public address (`PUBLIC_BASE_URL`), not
  on the dashboard's origin - the webhook is served by the API host, which is usually a
  different origin from the UI. Its shape is:

  ```
  {PUBLIC_BASE_URL}/api/v1/webhooks/triggers/{source}/{trigger_id}
  ```

  `source` is one of `github`, `email`, `linkedin`, `webhook`; `trigger_id` is an
  unguessable UUID. The dialog fills this in for you - copy it, do not build it by hand.

- **The signature** is `HMAC-SHA256` over the **exact raw request bytes**, keyed with
  the signing secret, hex-encoded, and prefixed with `sha256=`. It rides in a header
  that depends on the source:

  | Source | Header |
  |---|---|
  | `github` | `X-Hub-Signature-256` |
  | `email`, `linkedin`, `webhook` | `X-Signature-256` |

  GitHub signs deliveries natively under its own `X-Hub-Signature-256` header, so you
  give GitHub the secret and it does the signing. Every other source reuses the identical
  scheme under `X-Signature-256`, which whatever you point at the URL has to set itself.

The signature is not decoration. Without it, the URL is the only thing between a stranger
and your organization's model budget - and URLs leak: into logs, into a provider's
delivery history, into a screenshot in a support ticket. Anyone who has the URL could
fire the agent at will and spend against your caps. The secret is what makes a delivery
*authentic* rather than merely *addressed correctly*. A request whose signature does not
verify is refused with a `403` before the runner is ever reached; the secret is sealed
in the [vault](secrets.md) and never appears in a read, a listing, or the URL.

A verified delivery that has nothing to do - an inactive trigger, or a payload the
filter does not match - answers `202` exactly as a fired one does, so holding the secret
tells you nothing about which triggers exist. A body that is not a JSON object is a
`400`.

## A GitHub recipe (~5 minutes)

GitHub signs its own deliveries, so this is the quickest source to wire up. Create the
trigger with source **GitHub** first, copy its webhook URL and signing secret, then:

1. In the repository you want to watch, go to **Settings → Webhooks → Add webhook**.
2. **Payload URL** - paste the webhook URL from the trigger dialog.
3. **Content type** - choose `application/json`. Not `application/x-www-form-urlencoded`:
   the signature covers the exact bytes GitHub sends, and the form encoding changes them,
   so a form-encoded delivery verifies against nothing and comes back `403`.
4. **Secret** - paste the signing secret.
5. **Which events?** - choose *Let me select individual events*, tick **Issues**, and
   untick everything else. Only `issues` webhooks reach the fire path at all (the event
   type is read from the `X-GitHub-Event` header); anything else is discarded. Narrow
   *which* issue actions fire with the trigger's filter - it defaults to issue creation
   (`opened`).
6. **Add webhook.** GitHub sends a `ping`, which is not an `issues` event, so it will not
   fire the agent - that is expected.

When a delivery is refused, diagnose it in GitHub's **Recent Deliveries** tab on the
webhook: it shows the exact request and the response. A `403` there is a signature
mismatch - almost always the secret is wrong or the content type is not
`application/json`.

## The payload contract for relay-delivered sources

GitHub owns its payload shape. The other sources do not: `email` and `linkedin`
deliveries come from whatever relay you point at the URL - a Zapier or Make step, a
monitoring tool, a small script - and that relay decides what JSON to send. The filters
read specific field names, and **if the relay names a field anything else, the filter
silently never matches and the trigger simply never fires** - there is no error to tell
you why. Match these names exactly.

**Email** (`source = email`):

| Field | Used for |
|---|---|
| `from` | `sender_contains` filter |
| `subject` | `subject_contains` filter |
| `body` | appended to the agent's prompt (accepts `text` as an alias) |

```json
{ "from": "billing@acme.com", "subject": "Invoice #4021", "body": "…" }
```

Both filters are optional substrings, matched case-insensitively; with neither set, any
signed delivery fires.

**LinkedIn** (`source = linkedin`):

| Field | Used for |
|---|---|
| `author` | `author_contains` filter |
| `text` | `text_contains` filter, and appended to the prompt (accepts `body` as an alias) |
| `url` | appended to the prompt |

```json
{ "author": "Jane Doe", "text": "We are hiring…", "url": "https://www.linkedin.com/…" }
```

The catch-all `webhook` source has no filter - a verified delivery fires, and the whole
JSON body is appended to the prompt - so use it for anything whose shape does not fit
the two above.

## Signing a delivery yourself

For the generic `webhook` source (and to test any source by hand), you sign the request
yourself. Two footguns decide whether the signature verifies, because both change the
bytes:

- **Sign the bytes you send, and only those.** `echo` appends a trailing newline that
  gets signed but may not be sent, or sent but not signed; use `printf '%s'` and pass the
  body with `curl --data-raw` so nothing is added or interpreted.
- **Do not re-serialize.** Signing a dict and then letting your HTTP client re-encode it
  produces different bytes (reordered keys, different spacing). Sign a string and send
  that *same* string.

**curl:**

```bash
SECRET='your-signing-secret'
URL='https://api.example.com/api/v1/webhooks/triggers/webhook/<trigger_id>'
BODY='{"hello":"world"}'

SIG="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | sed 's/^.* //')"

curl -sS -X POST "$URL" \
  -H 'Content-Type: application/json' \
  -H "X-Signature-256: $SIG" \
  --data-raw "$BODY"
```

**Python** (httpx):

```python
import hashlib
import hmac

import httpx

secret = b"your-signing-secret"
url = "https://api.example.com/api/v1/webhooks/triggers/webhook/<trigger_id>"
body = b'{"hello":"world"}'

signature = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()

# content=body sends these exact bytes. json=... would re-serialize and sign nothing.
httpx.post(
    url,
    content=body,
    headers={"Content-Type": "application/json", "X-Signature-256": signature},
)
```

For the `github` source the algorithm is identical; only the header name changes to
`X-Hub-Signature-256`.

## Zapier and Make cannot do this without a code step

It is tempting to reach for a no-code webhook action in Zapier or Make. Neither has an
HMAC action: their standard "POST to a webhook" steps send the body but cannot sign it,
so every delivery arrives unsigned and is refused `403`. You have to add their **code
step** (Zapier's *Code by Zapier*, Make's *Custom JS / functions* module), compute the
`sha256=<hex>` HMAC over the exact body you are about to send, and set the
`X-Signature-256` header from it.

That works, but be honest about the cost: it is roughly an hour with a code step, not
five minutes of clicking. If you are only proving the trigger end to end, sign a request
by hand with the snippet above first.

## Testing locally

On a laptop `PUBLIC_BASE_URL` defaults to `http://localhost:8000`, so the URL the dialog
hands you is unreachable from GitHub or any hosted relay - they cannot see your machine.
Two ways through it:

- **Just use Run now.** Every trigger has a *Run now* action that fires it once on
  demand. It goes straight to the runner with **no signature and no webhook involved** -
  the fastest way to confirm the agent, its prompt and its budget behave, without any
  provider set up at all. Its one gap is that it does not exercise the signature path or a
  real payload, so it will not catch a wrong secret or a mis-named field.

- **Expose the port with a tunnel** when you do want to test the real webhook path. Point
  a tunnel at the API, set `PUBLIC_BASE_URL` to the tunnel's public address, and **create
  the trigger after that** - the URL is built from `PUBLIC_BASE_URL` at read time, so a
  trigger created before the change would still hand out a `localhost` URL.

  ```bash
  cloudflared tunnel --url http://localhost:8000
  # then set PUBLIC_BASE_URL to the printed https URL, restart the API,
  # and create the trigger
  ```

  Point the provider (or your signing script) at the tunnel URL and the delivery reaches
  your machine like any hosted one.
