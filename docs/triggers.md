# Setting up an event trigger

An **event trigger** fires an agent when something happens somewhere else. There are
two ways that reaches us, and which one a source uses is the source's own business
rather than yours:

- **Pushed.** A provider POSTs a signed payload - a GitHub issue, or anything that
  can send signed JSON (the **API** source).
- **Polled.** The platform reads a connected account on a schedule. **Gmail** is
  this: nothing is posted to us, so there is no URL to configure and no secret to
  keep. You connect the mailbox and that is the whole setup.
[Concepts](concepts.md#trigger) covers what a trigger *is* and how a fired run behaves;
[Governance](governance.md) covers what it spends and how a refusal is handled. This
page is what you do next: how to point a real provider at the webhook, what the
delivery has to contain, and how to test the whole thing from a laptop.

If you only need the agent to run on the clock, you want a **schedule**, not an event
trigger - no webhook, no secret, no provider to configure. Either kind can start from a
seeded **template** (`GET /trigger-templates`): a schedule template - "summarise my open
pull requests every weekday morning" - pre-fills the prompt and a sane cadence, and an
event template - "triage the new issue", "draft a reply to the email" - pre-fills the
prompt on its own source's message step, so neither starts from a blank box. Everything
below is for the event case.

## Where they live in the product, and what to call them

**Routines** is the umbrella - the nav, the page, the agent's own panel, the chat
sidebar and the dashboard card all use that one word, so a person meets the same
noun wherever they arrive. The two families under it stay distinct because they
behave differently: a **schedule** fires on the clock, a **trigger** fires on an
arrival. What was not allowed to differ was the umbrella, which is how the nav
came to say "Routines" over a panel headed "Schedules & triggers" (#594).

Four surfaces, one list:

| Where | What it is for |
|---|---|
| **Routines** (`/routines`) | Every routine in the organization, and the two ways to start one |
| An agent's **Availability** tab | Only that agent's, beside where its exposure is configured |
| The **chat** sidebar's Routines section | What the agent you are talking to does on its own |
| The **Routines** dashboard card | Soonest first, with how the last fire went - a routine failing every hour is invisible anywhere else on that page |

The dashboard card is addable from `Customize` and is on the default arrangement
under **Needs attention**. It reads the same org-wide list, so a reader who may
see the agents sees their routines; the outcome and cost on each row need
`runs:view` and are simply absent without it.

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

  `source` is one of `github` or `webhook` (the API source's wire name); `trigger_id`
  is an unguessable UUID. The dialog fills this in for you - copy it, do not build it
  by hand. **`gmail` has no URL**: a polled source has no inbound door, and a POST
  naming one is answered like any delivery with nothing to do.

- **The signature** is `HMAC-SHA256` over the **exact raw request bytes**, keyed with
  the signing secret, hex-encoded, and prefixed with `sha256=`. It rides in a header
  that depends on the source:

  | Source | Header |
  |---|---|
  | `github` | `X-Hub-Signature-256` |
  | `webhook` | `X-Signature-256` |

  GitHub signs deliveries natively under its own `X-Hub-Signature-256` header, so you
  give GitHub the secret and it does the signing. The API source reuses the identical
  scheme under `X-Signature-256`, which whatever you point at the URL has to set itself.
  A **polled** source signs nothing and holds no secret: it was not addressed, it was
  read, and the account's own OAuth grant is what authorized reading it.

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

## Rotating the secret, and editing the filter

The URL is the trigger's identity and never changes; the secret is a credential, and
like every other key in this product it can be **rotated** - a re-seal and a fresh
plaintext shown exactly once. `POST /agents/{agent_id}/triggers/{trigger_id}/rotate-secret`
mints a new secret, seals it, and returns the trigger with `reveal_secret` set once (the
same field create uses). Rotate the moment a secret might have leaked; the old one stops
verifying immediately. For a hook the platform registered itself (`auto_webhook`), the
rotation re-registers it with the new secret so its deliveries keep verifying and there
is nothing to reveal - unless the account can no longer register it, in which case the
trigger falls back to `manual` and the revealed secret is what you re-paste. A schedule
has no secret, so rotating one is refused.

Which issue actions fire is a **filter**, not a different trigger, so it is editable in
place: `PATCH` the trigger with a new `event_config` and it is re-validated against the
source's rules exactly as create validates it - an unknown key is refused rather than
stored to match nothing. The source and the secret are not editable this way; repointing
an event trigger at a different source is a new trigger, made by deleting this one and
creating that.

## Gmail (~1 minute, and no secret anywhere)

Gmail is polled, so the setup is a consent screen and nothing else.

1. **Connect the account.** *Routines → New event trigger → Gmail → Connect account*.
   That needs `mcp:manage`, the same permission every other connected account needs.
2. **Pick what fires it**: any new message, inbox only, or marked important. Narrow
   further with a sender or subject substring, or a Gmail label.
3. **Write the prompt**, or start from the "draft a reply" template.

There is no URL to paste and no secret to store, because nothing posts to us. What
you should know about how it reads:

- **Once a minute.** The heartbeat asks Gmail what arrived since it last looked, so
  the worst-case latency is a minute. That is deliberate: the alternative -
  `users.watch` into a Google Cloud Pub/Sub topic - is real-time and costs a topic
  and a subscription as *deployment* prerequisites, plus a registration that expires
  every seven days and needs something to renew it.
- **Connecting fires nothing.** The first read establishes where the mailbox is and
  answers empty, so connecting an account does not fire the agent once per message
  already in it.
- **A burst is bounded.** One tick reads at most 25 new messages in full. A mailing
  list dump does not become 400 agent runs; the position still advances, so the
  backlog is not re-read for ever.
- **One message can fire several triggers.** Unlike a webhook, whose URL names
  exactly one - "any message" and "marked important" on the same mailbox both fire.
- **A missed week repairs itself.** Google keeps about a week of history. A cursor
  older than that resynchronises to now rather than parking the mailbox for ever.

The deployment needs a Google OAuth client (`GOOGLE_CLIENT_ID` /
`GOOGLE_CLIENT_SECRET` - the same pair Google sign-in uses) with the Gmail API
enabled. Without one the card says so instead of offering a Connect button that
could only fail. Unlike GitHub, the client is the *deployment's* rather than each
organization's: Google's consent screen for a mailbox scope needs a verified
project, which an operator registers once and no tenant of theirs can register at
all.

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

GitHub owns its payload shape, and a polled source's is read by the adapter that
reads it - a Gmail trigger's filters are matched against the message itself, so
there is no contract for you to satisfy.

The one that is yours is the catch-all `webhook` source - **API** in the dialogs.
It has **no filter**: a verified delivery fires, and the whole JSON body is appended
to the prompt. Use it for anything no portal covers - watching a feed no provider
exposes an API for (a LinkedIn page, a marketplace listing), or any tool that can
POST - with whatever relay you write doing the watching.

There used to be an `email` source here, and it was this one wearing a different
name: it renamed two filter fields and asked you to run a relay - a Zapier or Make
code step, a small script - that signed and posted JSON at us, because nothing in
this product could receive mail. It was removed for the same reason `linkedin` was:
a dropdown entry whose name promises an integration that does not exist. Gmail
replaced it as a real connected account (above), and a relay-fed mailbox is the API
source with a documented example.

**A relay-fed email, as the API source:**

```json
{ "from": "billing@acme.com", "subject": "Invoice #4021", "body": "…" }
```

Nothing filters on those names any more, so the whole body reaches the prompt and
the agent reads it. If you want the *filtering*, connect the mailbox instead.

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

- **Just use Run now.** *Run now* fires either kind of trigger once on demand - a
  schedule fires one extra time with its cadence untouched, and an **event trigger fires
  too**, as a manual test-fire: the agent runs its base prompt with **no delivery context,
  no signature and no webhook involved**. It is the fastest way to confirm the agent, its
  prompt and its budget behave without any provider set up at all. An inactive (paused)
  trigger is respected - *Run now* does nothing to one. Its one gap is that it does not
  exercise the signature path or a real payload, so it will not catch a wrong secret or a
  mis-named field.

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
