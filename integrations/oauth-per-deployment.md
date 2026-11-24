# Per-deployment OAuth runbook (Google + Microsoft)

Operator prep for the native Google Workspace and Microsoft tools that arrive
with the upstream sync (Route C — upstream PR #2805, taken in the next sync).
This runbook exists so the first client deployment is not invented from
scratch. It covers setup only; it does not change any code.

**Status: prep.** The native tools are not in the fork yet. Do not register
clients for a deployment until the sync that lands them is merged and the
live consent flow has been exercised once in staging. Live Google/Entra
consent flows are untested by anyone so far — budget half a day of admin
setup plus a live test pass for the first deployment.

## Why one client per deployment

Redirect URLs are deployment-specific, and there is no shared published
client (upstream's Desktop PKCE decision is a recorded no-go). **Each client
instance needs its own Google Cloud project + OAuth client and its own Entra
app registration.** That is recurring work per client, not a one-off.

> **Undecided — who holds the OAuth clients?** Whether T3's team registers
> and owns the Google OAuth client + Entra app for each client deployment,
> or the client's IT does it, is **not decided**. Do not assume an answer:
> whoever holds them also holds the ability to rotate secrets and to see
> the consent screen. Decide this before the first client rollout; the
> steps below are the same either way.

The Composio path is unchanged and separate: one Composio project + keys
per deployment (`COMPOSIO_API_KEY`, `COMPOSIO_CATALOG_API_KEY`,
`COMPOSIO_AUTH_CONFIGS`, stable `COMPOSIO_USER_NAMESPACE`). Native tools
carry no Composio per-call meter; Composio keeps serving Notion, GitHub
and the long tail.

## Google — one Cloud project + OAuth client per deployment

1. In the [Google Cloud console](https://console.cloud.google.com), create
   a project for the deployment (one per client instance, not shared).
2. Enable the six APIs the native products need:
   `gmail.googleapis.com`, `calendar-json.googleapis.com`,
   `drive.googleapis.com`, `docs.googleapis.com`, `sheets.googleapis.com`,
   `slides.googleapis.com` (the setup wizard prints the exact
   `gcloud services enable …` command).
3. Create an OAuth client (Web application) in **APIs & Services →
   Credentials**. Add the redirect URI exactly as the setup wizard shows
   it (copy it from the wizard — it is deployment-specific).
4. Enter the client ID and secret once as the deployment's
   `google_oauth_app` secret. Members then connect with one click.
5. Consent is delegated OAuth with `access_type=offline` and
   `prompt=consent`, so a refresh token is always issued. Scopes are
   least-privilege per product: `gmail.readonly` (read), `gmail.modify`
   and `gmail.send` only where a write is approved, `drive.readonly`,
   `calendar.readonly`.

### Internal vs External consent — read this before choosing

`gmail.readonly`, `gmail.modify` and `gmail.send` are **restricted scopes**:
an **External** consent screen needs Google verification for them, and
until verification completes the app stays in Testing — tokens expire
after **7 days**. A Workspace **Internal** app (the OAuth client lives in
the same Google Workspace org as the users) avoids verification and the
7-day expiry entirely. Prefer Internal whenever the deployment's users are
all in one Workspace org; use External only when users span orgs, and
budget the verification review in that case.

A Google service account with domain-wide delegation is also supported by
the native tools for org-wide automations; it is a separate setup from
delegated OAuth and needs a Workspace admin to authorize the client ID
with the same scopes.

## Microsoft — one Entra app registration per deployment

1. In the [Entra admin center](https://entra.microsoft.com), register an
   app for the deployment (one per client instance). Add the redirect URI
   exactly as the setup wizard shows it.
2. Add the delegated permissions the native products need, least-privilege:
   `Mail.Read`, `Calendars.Read`, `Files.Read.All`, `Chat.Read`. The
   wizard lists the exact scope set per product.
3. Enter the client ID (and secret, where app-only access is needed) once
   as the deployment's `microsoft_oauth_app` secret.
4. Delegated OAuth works for work or personal accounts where Graph
   allows. **Excel and ordinary Teams posting require delegated OAuth.**
   App-only access (client secret or certificate) is for organization-wide
   automations; app-only Teams watches additionally need a directory
   object ID. Exchange Online uses Graph; on-premises Exchange/EWS is out
   of scope.

## After the clients exist

- Run the live consent test in staging: connect a Google account and a
  Microsoft account through the console, exercise one read per product
  (Gmail search, Calendar list, Drive search, Outlook search, Teams
  list), and confirm the token refreshes.
- Record per deployment: the Google project ID, the Entra app (client) ID,
  which consent type Google uses (Internal/External), and who holds the
  clients (once decided above). Store secrets in the deployment's vault
  references, never in this repo.
- Writes stay closed until the write policy is decided: land reads first,
  then open writes per operation through the T3OS approval + execution-test
  process. Do not enable native `send_message`, `create_event` or
  `append_rows` as silently available.

## Sources

- Upstream PR #2805 / issue #2797 (native business-app tools); the
  per-provider setup wizard data in upstream `setup.py`.
- `google-microsoft-incorporation-plan.md` and `connections-alignment.md`
  in `~/workspace/agenticos-align/` (Route C decision, dedup rule and
  write policy — both still undecided at the time this runbook was
  written).
