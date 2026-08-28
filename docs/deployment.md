# The deployment itself

Most of this product is about agents. This page is about the thing they run
inside.

**One installation, with a name, a mark, a rule about who may join it, and a switch
that closes it.** All of it lives in a single database row and is edited from
`/admin/settings` by whoever holds `is_app_admin` — no redeploy, no environment
variable, no rebuild.

!!! info "Why that authority, and not a permission"

    A permission is scoped to an organization. This row is not in one.

    It is the same authority that already administers users and tenants across the
    installation.

## Identity

| Field | Where it shows |
|---|---|
| Name | The sidebar, the sign-in header, the browser tab, the OpenGraph card, and every email this deployment sends |
| Tagline | Beside the name in the tab title and on a shared link |
| Description | The page description and link previews |
| Logo | Wherever the name appears — the brand link, the sign-in header, the legal pages |
| Favicon | The browser tab |
| Footer text | Under the sign-in form |
| Terms URL, Privacy URL | Every link that otherwise offers the built-in `/legal/*` pages |

!!! note "A null column means *the built-in*, not *empty*"

    An operator who clears a field is asking for the default back, not for a
    sign-in header with no name on it. The API answers *overrides* and each
    renderer resolves a null against its own built-in.

An operator who has never opened the page has no row at all. The console resolves
a null against `APP_NAME` and `SITE` in `frontend/src/lib/`; the backend resolves
it against `settings.PROJECT_NAME` for the mail it sends itself.

Two constants for one product name can drift, so
`backend/tests/test_deployment_settings.py` pins them equal. It reads the
frontend's `constants.ts` and compares it to `Settings.PROJECT_NAME`'s class
default — the same bargain `TestFrontendToolCatalog` takes with the tool catalog.

### The two images

Uploaded through `POST /api/v1/admin/settings/{logo,favicon}` and stored the way
every other image in this platform is: the bytes go to the configured file
storage and the key goes to a column. **The key is never taken from a request
body** — a caller who could name it could point this deployment's public logo at
whatever the storage backend holds — and the stored filename is minted from the
validated content type rather than from the upload's own name, because these files
are served from the origin the app's own pages run on and `logo.html` there is a
script.

JPEG, PNG, WebP and GIF, up to 2MB, which is the one definition of "an image this
platform accepts".

!!! danger "SVG is deliberately absent"

    It is a document that may carry script, and these files are served from the
    origin the app's own pages run on. ICO buys nothing a PNG favicon does not.

The branding response carries a **version**, not a URL. The address is constant
(`GET /api/v1/branding/{logo,favicon}`) and the bytes are served `immutable` for a
year, so what a client needs from the row is whether an image exists and when it
last changed; the `?v=` built from that is the only reason a replacement ever
appears. A URL would also be one every client had to rewrite, since in any real
deployment the API is not on the same origin as the pages.

## Who may register

`signup_mode`, applied in `app/services/signup_policy.py` — the one place, and it
gates **both** paths that mint an account.

| Mode | Effect |
|---|---|
| `open` | Anybody may register. The default, and what every deployment before this feature was. |
| `invite_only` | Only an address some organization has actually invited. |
| `closed` | Nobody registers, by any route — an invitation does not override it. |

Across all three, a non-empty `allowed_email_domains` narrows who may register at
all. **An invitation overrides that list** — somebody holding `members:invite`
named the address on purpose, and a domain list is deployment policy for strangers
rather than a veto over a deliberate act. `closed` is overridden by nothing,
because "closed" that lets some registrations through is not closed.

**`closed` means closed, and there is no administrator-creates-an-account path.**
Deliberately: an account needs a password its owner chose, so adding somebody means
opening registration *to them* — which is what `invite_only` is for. A mode that
let an administrator mint accounts would be a third path minting one, and the two
that already exist are the whole reason `signup_policy` is a module rather than a
check inside `register`. So a deployment that has to admit one more person switches
to `invite_only` and invites them.

Three more things about this that are easy to get wrong, and were:

**The first user is always admitted.** A fresh installation has no accounts, so
its administrator does not exist yet; a closed deployment that also refuses the
person who would open it is one nobody can enter, with no console to fix it from.
`register` already promotes that first account to `is_app_admin`, and the policy
defers to the same fact.

**`invite_only` exists because closing registration would otherwise break
invitations.** `InvitationService.accept` requires an existing signed-in user, so
an invited person has to register first. The policy asks
`invitation_repo.first_pending_admitting`, which is cross-tenant by construction —
registration happens before an organization is chosen. What keeps that safe is
where the answer goes: the policy turns it into a boolean refusal, so a stranger
probing the sign-up form learns that somebody invited the address and never which
organization did.

**How an invitation is recognised depends on whether the registration carries its
token**, and the two answers cover different shapes:

| Arrives with | Recognised by | Which shapes it admits |
|---|---|---|
| A token (`invitation_token` on the sign-up body) | `invitation_admission.admits` | Any live invitation that admits the address — including a link constraining **no** address, which is the shape nothing else can see |
| No token | `invitation_repo.first_pending_admitting` | An email invitation for that address, or a link scoped to its domain |

The token is the only proof available for a shareable link with neither an address
nor a domain on it. A query over the submitted address cannot recognise one, so
honouring it *without* proof of possession would turn a single open link anywhere in
the deployment into open registration for the whole internet. Holding the token is
that proof.

A token that names nothing live falls through to the address question rather than
refusing: a stale link in a bookmark should not turn a registration that would
otherwise be allowed into an error about something the person cannot fix.

**Registering with a token does not accept the invitation.** It admits the account
and nothing else; joining the organization is still `InvitationService.accept`, which
the client calls once it has a session. A token in an unauthenticated sign-up body
that also granted membership would be a membership grant on a public route.

The console carries it across the redirect that used to lose it. An invitee with no
account opens `/invitations/<token>`, `AuthGuard` bounces them to
`/login?returnTo=/invitations/<token>`, and `src/lib/invitation-links.ts` reads the
token back out of that `returnTo` so "create an account" points at
`/register?invitation=<token>`. Before that, the only route onward was a plain link
to `/register`, and the form then refused somebody holding a valid invitation.

**A link with a `max_uses` bounds accounts, not only joins.**

`used_count` counts acceptances, and acceptance needs a session — so a ceiling read
off it alone bounded nothing a registration did. One one-use link posted in a channel
admitted as many accounts as anybody cared to create, on the deployment that had just
closed sign-up.

So a use is **reserved** for the registering address first: `reserved_emails` on the
row, and `used_count + reserved_emails` is what "used up" means. The reservation is a
single conditional `UPDATE`, because two registrations racing on the last use would
both read the same count otherwise.

Accepting moves the address out of the list as it increments the count, which
conserves it — somebody who registered through a one-use link can still join.

A reservation nobody accepts stays spent (`max_uses` is how many people a link
admits, and an account created with it was admitted), and it dies with the
invitation.

**Signing in with a provider carries the invitation too.** The token is put on
`/oauth/google/login?invitation=…` and held in the session across the round trip,
because the provider redirect is not ours to add a parameter to. Without it,
`invite_only` refused the Google button for exactly the links that need a token —
one constraining neither an address nor a domain — while the password form beside it
accepted the same person.

**Signing in with a provider is a registration too.** `get_or_create_oauth_user`
is the second path that creates an account, and nothing about a Google callback
looks like a sign-up — so a deployment with `closed` and a Google button was wide
open until both were gated. Somebody who *already* has an account is not re-gated:
closing registration closes registration, and locking a member out of a deployment
they belong to is not what the setting says.

The sign-up form reads the policy from the public branding endpoint and says the
rule **before** anybody types. A form that accepts an address and then reports
"that email domain cannot register" is a form that lies; the visitor has no way to
know the rule exists and reads the refusal as the product being broken. That is
also why the allowed domains are published: they are not a secret, and the
deployment is on the company's own host.

## Finding one tenant among all of them

`GET /admin/organizations` is the only surface that answers *what tenants exist*,
and it is app-admin only for the reason it is useful: it is cross-tenant by
construction. It answers a page of organizations with each one's member and agent
counts and its earliest owner — who to ask about it. Every owner field is null
together, for an organization whose last owner left, which is a state only the
deployment admin can fix and therefore one they have to be shown.

| Parameter | |
|---|---|
| `search` | Name, slug, or the owner's address. The term is text, not a pattern — `100%` finds the tenant called that rather than all of them |
| `sort_by` | `name`, `slug`, `members`, `agents`, `created_at`. Anything else is a 422 |
| `sort_dir` | `asc` / `desc`, defaulting to newest first |
| `kind` | `personal`, `team`, or `all`. Every account is given a personal organization at sign-up, so on most deployments they are most of the list |
| `skip`, `limit` | One server page, up to 100 |

**All of it happens in SQL, before `OFFSET`/`LIMIT`**, and `total` counts what was
narrowed to rather than the deployment. That is the difference between a sort and
the appearance of one: a page sorted after it arrives claims a whole-collection
order that fifty rows cannot deliver, which is why the admin's tenant list carried
no controls at all while the route answered none (#921). The order breaks ties on
the id, so paging a column where rows share a value lists each of them once.

A column outside the set is refused by name rather than matched against nothing,
for the two reasons `GET /runs` refuses one: an empty page reads as *this
deployment has no tenants*, and an `ORDER BY` assembled from a query string is an
injection surface.

## An app admin cannot lock the deployment out through the console

!!! warning "The self-inflicted lockout this prevents"

    On the single-admin install `make platform-bootstrap` produces, a stray click
    on your own row ended administration until somebody reached a terminal.
    Recovery is `agenticos cmd create-app-admin <email>` from a shell — the
    email is a required argument.

`is_active` is enforced on the next request and `is_app_admin` is what the admin
pages read, so an app admin acting on **their own** row from `/admin/users` could
sign themselves out, drop `/admin`, or delete the account.
`UserService.admin_update` and
`admin_delete` refuse the self-suspend and the self-delete, and the drawer does
not offer Suspend, Demote or Impersonate on your own row (Delete stays, visible
and refused, because "why can I not delete myself" has an answer worth showing).

The deployment cannot be left with no app admin through the API at all: the one
global privilege is granted only by CLI (`agenticos cmd create-app-admin`) and
there is no request that clears it, so the set of app admins shrinks only by
deletion — and deleting the *last* one is deleting yourself, which is refused.
Removing an admin genuinely leaving is another admin's action, which is also what
keeps the audit trail readable. Recovery, if it is ever needed, is still
`create-app-admin` from a shell on the deployment.

That argument is about the *set*, and for a while the code was about one row.

Two admins deleting each other were each not deleting themselves. They locked
different target rows, never contended, and both committed — zero app admins,
recoverable only by writing to the database (#1208).

So an admin deletion takes `SELECT ... FOR UPDATE` over the app-admin set, ordered by
id, before it decides. The second request waits, re-reads the set once the first has
committed, and is refused for emptying it.

Ordered, because two requests taking the same rows in different orders is a deadlock
rather than a queue. And taken on every admin deletion rather than only on an
admin's: deleting a user is an administrator's action, not a hot path, and a total
order is worth more than the contention it costs.

## Notices, and closing the deployment

**The announcement** is one sentence with one of three styles, shown above every
page to signed-in users until they dismiss it. It is the one field on this row that
is *not* on the public endpoint: an announcement is an operator talking to the
people using the deployment — an upgrade window, who to ping — so it has its own
route, `GET /api/v1/branding/notice`, behind a session.

Dismissal is keyed on the **message itself**, in the browser's own storage. A flag
would make the next announcement invisible to everybody who dismissed the last
one; the settings row's timestamp would un-dismiss a notice whenever the
deployment was renamed. The text is what changed, so the text is the key. Storage
that refuses to be read or written — a privacy mode, an embedded webview — means
"nothing dismissed" rather than an exception: thrown during render it would take the
dashboard down for every signed-in user, and the banner still closes for as long as
the page is open.

**Maintenance mode holds the API shut**, not just the console.
`app/core/maintenance.py` is a pure-ASGI middleware above the routes, so a page
somebody already has open stops working — which is the whole difference between a
maintenance mode and a banner. Its allow-list is short and is tested entry by
entry:

- `/health*` — a readiness probe that fails during a window is an orchestrator
  restarting the container the operator is working in.
- `/api/v1/branding` — the closed page has to be able to say what this deployment
  is called and why it is shut.
- `/api/v1/auth/*` — an administrator has to be able to sign in **while** the
  window is open.
- `/api/v1/admin/*` — and then reach the switch.
- The docs and the OpenAPI schema, which serve no data.

Everything else is a 503 with `Retry-After`. It reads no session at all — that
would mean verifying a token above the dependency graph — so widening the path to
`/api/v1/admin/*` does not widen the authority: `CurrentAppAdmin` refuses a
non-admin there exactly as it always did.

**It fails open.** A gate that cannot read its own switch — a Redis blip, a
migration that has not run — lets traffic through, because the alternative turns an
infrastructure hiccup into a total outage nobody scheduled.

The verdict is cached in the Redis every worker already shares: written **after the
commit**, so the switch is immediate and the cache can never advertise a state the
database rolled back — published eagerly, a request that then failed left a
disabled window reopening the deployment for up to the TTL. It carries a 30-second
TTL as well, so a write that never reached Redis heals itself instead of leaving the
deployment open through a window somebody scheduled.

**And an already-open page hears about it.** The branding context is resolved once by
the root server layout and never changes for the life of a page, so a window opened
afterwards left every open tab on a dashboard whose every request had begun answering
503, with nothing on screen saying why — and closing one left a tab on the
maintenance screen until somebody reloaded. `GET /api/v1/branding/notice` carries the
maintenance verdict beside the announcement and is polled once a minute, which is one
request for both answers rather than two that can disagree about one row.

In the console, the administrator sees a strip rather than the closed page. They
are the only person who can end the window, and a maintenance mode that also hides
the switch is an outage.

## How much one account may take up

Two ceilings, both on the same row and both **null by default — and null is no
limit rather than "not configured"**. A self-hosted deployment for one company
wants neither; a deployment open to sign-ups wants both, because one account can
otherwise mint tenants without bound.

| Setting | Counts | Does not count |
|---|---|---|
| Organizations per account | The organizations an account **owns**, personal one included | Ones somebody else invited them into |
| Agents per organization | Agents the organization holds | Archived agents |

**Every transition into the counted state is checked, not only a create.** A ceiling
enforced on new rows alone is one that gets walked past sideways: an organization at
its agent limit archives one, creates a replacement and restores what it archived,
and an account at its organization limit is handed somebody else's through
`transfer_ownership`. So `unarchive` and `transfer_ownership` ask the same question
`create` does.

**And the count is taken under a lock.** Reading `count(...) >= limit` and then
writing is two statements, so two requests both pass the count and both insert — the
ceiling exceeded deterministically, by clicking twice. No constraint can express "at
most N rows like this", so `app/db/locks.py` takes a transaction-scoped advisory lock
on the *subject* of the ceiling: two requests about one account queue, requests about
different accounts never meet, and the lock is released by the commit or the
rollback. Only where a limit is set, so an uncapped deployment pays nothing.

Both exclusions are the point of the design rather than details of it. Being
invited into ten organizations is somebody else's decision, and a ceiling one
person cannot control is a ceiling that locks them out of creating their own. And
archiving is how an agent is retired — a ceiling a retired agent went on
occupying would make the only way back under it a delete, which takes the version
history and the run attribution with it.

The refusal names the ceiling and the count it was measured against
(`{"limit": 5, "held": 5}`), so "why can I not" is answered by the response
rather than by an administrator's memory. It is raised in the service that
creates the thing, not at the route, because the route is not the only way in.

Zero is refused by the schema: an account that may own no organizations is an
account that cannot be created, since sign-up gives every one of them a personal
organization.

## The row

One row for the whole installation, guarded by the database rather than by a
convention nobody can see: `singleton` is unique and constrained to true, so a
second identity is an `IntegrityError` instead of a deployment that quietly has two
and serves whichever one a query ordered first. The write is a single
`INSERT ... ON CONFLICT DO UPDATE`, because a read-then-insert races itself the
moment two administrators save from two tabs.

**Nothing is seeded.** No row means every default, which is exactly the state of a
deployment nobody has configured — and it matters because the public branding
endpoint is unauthenticated and reached on every cold page load, so a read-through
that created a row would let a stranger provoke an `INSERT`.

Every write is audited into `app_admin_audit_logs`, naming the **fields** and never
their values: an announcement and a domain list are both operator text, and an
audit row outlives the request body it came from.

## A refusal from this deployment always looks the same

Worth saying here because closing a deployment is the feature most likely to produce
one a person has never seen. `app/api/exception_handlers.py` puts **every** refusal in
`{"error": {"code", "message", "details"}}`:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Agent not found",
    "details": { "agent_id": "…" }
  }
}
```

That covers domain exceptions, schema validation,
and since #917 `HTTPException` too, which covers a 405, an unmatched path and the
twenty-two routes that raise one directly. Two shapes on the wire means every caller
either handles both or silently mishandles one.

A wrong-method request used to answer **500** rather than 405, on every route.
OpenTelemetry's FastAPI instrumentation derives a span name by walking `app.routes`,
and its `Match.PARTIAL` branch — which is exactly "the path matches and the method
does not" — reads `.path` unguarded; FastAPI 0.141 puts `_IncludedRouter` objects in
that list and they have none. `app/core/otel_compat.py` supplies, for that branch,
the same fallback upstream already uses in the branch it did guard. Still unfixed
upstream as of 0.65b0, and `tests/test_otel_route_details.py` fails when it is fixed,
which is when the module goes away.

## Recap

- The deployment's identity is **one row**, edited from `/admin/settings`, and a
  null column means *the built-in* rather than *empty*.
- `signup_mode` is applied in **one place** and gates both paths that mint an
  account. An invitation overrides a domain list; nothing overrides `closed`.
- An app admin **cannot lock themselves out** through the console.
- Every refusal from this deployment looks the same, whichever layer produced it.
