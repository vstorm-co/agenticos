# The deployment itself

Most of this product is about agents. This page is about the thing they run
inside: **one installation, with a name, a mark, a rule about who may join it, and
a switch that closes it.** All of it lives in a single database row and is edited
from `/admin/settings` by whoever holds `is_app_admin` — no redeploy, no
environment variable, no rebuild.

That authority is deliberate and it is not a permission from the catalog. A
permission is scoped to an organization; this row is not in one. It is the same
authority that already administers users and tenants across the installation.

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

**A null column means "the built-in", not "empty".** An operator who has never
opened the page has no row at all, and one who clears a field is asking for the
default back rather than for a sign-in header with no name on it. So the API
answers *overrides* and each renderer resolves a null against its own built-in —
the console against `APP_NAME` and `SITE` in `frontend/src/lib/`, the backend
against `settings.PROJECT_NAME` for the mail it sends itself.

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
platform accepts". SVG is deliberately absent: it is a document that may carry
script. ICO buys nothing a PNG favicon does not.

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
| `closed` | Nobody registers. An administrator creates accounts. |

Across all three, a non-empty `allowed_email_domains` narrows who may register at
all. **An invitation overrides that list** — somebody holding `members:invite`
named the address on purpose, and a domain list is deployment policy for strangers
rather than a veto over a deliberate act. `closed` is overridden by nothing,
because "closed" that lets some registrations through is not closed.

Three things about this that are easy to get wrong, and were:

**The first user is always admitted.** A fresh installation has no accounts, so
its administrator does not exist yet; a closed deployment that also refuses the
person who would open it is one nobody can enter, with no console to fix it from.
`register` already promotes that first account to `is_app_admin`, and the policy
defers to the same fact.

**`invite_only` exists because closing registration would otherwise break
invitations.** `InvitationService.accept` requires an existing signed-in user, so
an invited person has to register first. The policy asks
`invitation_repo.any_pending_admitting`, which is cross-tenant by construction —
registration happens before an organization is chosen — and answers a boolean
rather than a row, so a stranger probing the sign-up form cannot enumerate tenants
with it.

Two shapes of invitation admit and one deliberately does not: an email invitation
for exactly that address, and a link scoped to the address's domain. A link with
neither an address nor a domain does not, even though anybody holding it may join
once they have an account — the register request carries no token, so honouring it
would turn one open link anywhere in the deployment back into `open` for the whole
internet.

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

## Notices, and closing the deployment

**The announcement** is one sentence with one of three styles, shown above every
page to signed-in users until they dismiss it. It is the one field on this row that
is *not* on the public endpoint: an announcement is an operator talking to the
people using the deployment — an upgrade window, who to ping — so it has its own
route, `GET /api/v1/branding/notice`, behind a session.

Dismissal is keyed on the **message itself**, in the browser's own storage. A flag
would make the next announcement invisible to everybody who dismissed the last
one; the settings row's timestamp would un-dismiss a notice whenever the
deployment was renamed. The text is what changed, so the text is the key.

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

The verdict is cached in the Redis every worker already shares: written eagerly
when an administrator saves, so the switch is immediate, and carrying a 30-second
TTL as well, so a write that never reached Redis heals itself instead of leaving
the deployment open through a window somebody scheduled.

In the console, the administrator sees a strip rather than the closed page. They
are the only person who can end the window, and a maintenance mode that also hides
the switch is an outage.

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
