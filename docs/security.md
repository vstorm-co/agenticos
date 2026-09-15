# Security

This page is what a HIPAA- or SOC 2-shaped security review hands over: the trust
boundaries, what data leaves the deployment and to whom, what is encrypted where,
and a controls matrix that names — for each control — the mechanism in this
codebase that satisfies it and the test that holds it true.

It describes what **is**, not what would be nice. A row with no mechanism says so,
and links the issue that would build it. For how to report a vulnerability and the
production hardening checklist, see [`SECURITY.md`](https://github.com/vstorm-co/agenticos/blob/main/SECURITY.md)
at the repository root; this page is everything else, in one copy.

Two neighbouring pages answer the questions a review asks next and are not
repeated here: [Data protection](data-protection.md) for where personal data
lives, what a deletion actually reaches and which gaps are still open, and
[Licences](licenses.md) for every third-party component the images ship.

## Threat model

The platform is self-hosted and multi-tenant. The design assumption is that the
operator's infrastructure is trusted and every request into it is not, so the
boundaries that matter are the ones a request crosses on its way to the data.

| Boundary | What crosses it | Trusted on the far side? |
|---|---|---|
| Browser → BFF (the Next.js route handlers) | A session cookie, the organization header, form input | No — but the BFF does not verify the cookie: it reads the `httpOnly` `access_token` and forwards it as a bearer header (`frontend/src/lib/platform-proxy.ts`). It is a credential-forwarding boundary; verification is the API's job |
| BFF → API (FastAPI) | A JWT bound to a DB session, the `X-Organization-Id` header | No — the token is verified per request, the session is checked for revocation, and the org is resolved from the token |
| API → PostgreSQL / Redis | Queries and cache reads, over TLS when configured | Yes — the store is the operator's; what it protects at rest is under "What is encrypted where" |
| API / worker → model providers, channels, MCP servers, search vendors, Logfire | Prompts, tool calls, queries, replies, traces | No — these are third parties; what reaches them is a per-agent decision, except deployment-wide tracing (below) |
| Worker → connectors (Google Drive, S3, …) | Credentials unsealed from the vault, fetched documents | No — a connector credential is a vault secret referenced by id |

Authority inside a tenant is never a role name on a route: it is a membership row
plus the permission catalog (`app/core/permissions.py`), resolved per resource.
Two callers who share a role can reach different rows, because a grant on one
resource widens what a role allows without promoting the member.

## What leaves the deployment

Nothing phones home. Every outbound call is one the deployment configured, and
each is a boundary a client's review will ask about.

| To | What | When |
|---|---|---|
| The configured model provider | The prompt, the model's output, tool arguments and results | Every run — unless the model runs on the operator's own infrastructure, in which case nothing leaves |
| The configured channel (Slack, Telegram, Mattermost) | The agent's generated replies — text, images and attachments | Whenever an agent is exposed through that channel; each `send_message` posts to the provider (`app/services/channels/`) |
| Logfire | Traces, which carry prompts and outputs unless the agent says otherwise | Two independent paths. A per-agent observability token traces that agent, and its `content` mode decides how much the span carries - `none` reduces it to timing, tokens, cost and tool names (#1413). A deployment-wide `LOGFIRE_TOKEN` instruments **every** run, in the API and in the Prefect worker alike (`app/core/logfire_setup.py`), so with it set, the content of any agent that did not ask for `none` leaves; an agent that did is pinned to content-free instrumentation on that tracer too (`suppress_content`), so the mode holds on both paths, and a specialist of that agent inherits it, written inline or invented mid-run. One gap it does not cover: an attach that fails, which is logged and left. Neither path is on by default. There is deliberately no filtered middle ground - a partly-scrubbed export is a guarantee nobody can audit ([#1616](https://github.com/vstorm-co/agenticos/issues/1616)) |
| MCP servers | Tool calls and their arguments | Only for the tools an agent is bound to |
| A web-search vendor (Tavily, DuckDuckGo) | The search query | Only when the search capability is granted |
| An embedding provider | Document text, at ingestion | Only for a knowledge base whose provider is remote |

## What is encrypted where

There is one application-level encryption mechanism, and it is deliberately the
only one: the vault (`app/core/vault.py`). Every **connector and API credential**
at rest is sealed in a per-owner envelope whose wrapping key is derived, through
HKDF, from the organization (or user) it belongs to — so a ciphertext copied into
another organization's row fails to unwrap. The master key is rotatable without
re-encrypting the payloads.

Not everything the platform stores is a vaulted credential, and this is stated
plainly because a review will find it:

- **Short-lived bearer tokens** — organization invitations
  (`OrganizationInvitation.token`), channel-link requests
  (`ChannelLinkRequest.token`) and conversation share links
  (`ConversationShare.share_token`) — are random `String(64)` columns looked up by
  equality, not vault-sealed. Whoever holds the value can use it, so they are
  protected by expiry and single use rather than encryption. Session refresh
  tokens are the exception that is hashed at rest (`sessions.refresh_token_hash`).
- **Uploaded and chat files** sit on the API container's filesystem in the clear
  (`app/services/file_storage.py`) — protected only by volume encryption.
- **Message bodies, `rag_documents` and their vectors, and sandbox workspaces**
  are stored as plaintext columns, pgvector rows and workspace files. The vault
  seals credentials, not content; at-rest protection for these is disk-level.

An S3-compatible file backend with server-side encryption is the app-level answer
for object storage and is tracked in
[#1423](https://github.com/vstorm-co/agenticos/issues/1423).

## Controls matrix

One row per control, the mechanism that satisfies it, and the test that holds it
true. Framed against HIPAA §164.312 technical safeguards and SOC 2 CC6–CC8.

### Access control · HIPAA §164.312(a) · SOC 2 CC6

| Control | Mechanism | Held by |
|---|---|---|
| Tenant isolation, even when the caller owns the row | `resolve_access` refuses a resource whose `organization_id` differs before the ownership check (`app/services/access.py`) | `test_resource_access.py::TestTenantBoundary`, `test_conversation_tenant_isolation.py`, `test_platform_flows.py` |
| Permission on every collection route | `require(*perms)` route dependency on listing, creating and catalog routes (`app/api/deps.py`), catalog in `app/core/permissions.py` | `test_platform_routes.py::TestEachRouteDemandsItsOwnPermission` |
| Per-resource routes authorize in the service, not on the route | A route acting on one agent, skill or collection carries no `require()` gate — a role gate would refuse a grant-holder before the grant applied — and calls `resolve_access` instead (`app/services/access.py`) | `test_platform_routes.py::TestEveryPlatformRouteIsGuarded` (every route is gated or service-decided) |
| A grant widens access without promoting the member | Per-resource `resolve_access` takes `max(role scope, grant)` (`app/services/access.py`) | `test_resource_access.py::TestGrantsWidenAccess`, `::TestPermissionsGrantsCannotWiden` |
| A channel mention runs as the sender, not the bot | A linked, active sender's own `AuthContext` is used (`app/services/channels/mentions.py`) | `test_channel_mentions.py::TestAnswer::test_the_run_carries_the_senders_own_role` |

### Authentication · HIPAA §164.312(d) · SOC 2 CC6

| Control | Mechanism | Held by |
|---|---|---|
| JWT (HS256), bcrypt passwords | `app/core/security.py` — `verify_token`, `get_password_hash` | `test_security.py`, `test_auth.py` |
| API keys compared in constant time | `secrets.compare_digest` (`app/api/deps.py`) | `test_auth.py`, webhook HMAC checks in the channel adapters |
| DB-backed sessions with revocation | `sessions` table + `SessionService`; token bound to a `sid` claim (`app/services/session.py`, `app/api/routes/v1/sessions.py`) | `test_session_verify.py`, `test_session_revocation.py` |
| Login rate limiting | `enforce_auth_limit` (`app/api/deps.py`) | `test_auth_rate_limit.py` |
| Single sign-on against the deployment's own identity provider | Generic OIDC by discovery — authorization code with PKCE, `email_verified` required, the account keyed on `sub` (`app/core/oauth.py`, `app/api/routes/v1/oauth.py`). Entra ID, Okta, Keycloak; configured in [Single sign-on](configuration.md#single-sign-on-generic-oidc) | `test_oidc_sign_in.py` |
| The sign-up policy gates SSO as it gates the form | `check_may_register` inside `get_or_create_oauth_user` — `invite_only` and the domain allow-list refuse a provider sign-in too (`app/services/user.py`) | `test_oidc_sign_in.py::TestTheRoundTrip`, `test_signup_policy.py` |
| Group-to-role mapping, SAML, SCIM | **Not yet** — people sign in through the provider; an administrator places them | — |

### Audit controls · HIPAA §164.312(b) · SOC 2 CC7

| Control | Mechanism | Held by |
|---|---|---|
| Governance-relevant mutations recorded, in the request's transaction | `record_audit` (`app/core/audit.py`) at the mutating service — secret rotation, skill / sync / MCP binding, membership, sharing, approvals, exports and more; written to `app_admin_audit_logs`. It is not blanket coverage of every write (knowledge-base CRUD, for one, is not audited) | `test_skill_binding_audit.py`, `test_sync_source_audit.py` |
| The trail is readable by an auditor | `GET /audit`, gated on `audit:read` (`app/services/audit.py`) | `test_audit_service.py` |
| Exporting the trail (CSV/JSONL) | `GET /audit/export` over a window, gated on `audit:read`, recording its own read in the trail; the run, approval and spend exports each do the same (#1422) | `test_exporting.py` (the export and its own audit entry) |
| Tamper evidence (a hash chain) | **Not yet** — [#1622](https://github.com/vstorm-co/agenticos/issues/1622) | — |

### Integrity · HIPAA §164.312(c) · SOC 2 CC8 (change management)

| Control | Mechanism | Held by |
|---|---|---|
| A spec is refused at publish, never at run time | `validate_spec` (`app/services/agent_registry.py`) — unknown capability, ungranted scope, wrong-kind or cross-org `secret_id`, a personal MCP connection | `test_agent_registry.py`, `test_capability_secrets.py::TestPublishValidation` |
| A budget is checked before the model request, and cost recorded even on failure | `BudgetGuard.wrap_model_request` gates before the call (`app/agents/capabilities/budget/`); the run's cost is written in a terminal `finally` (`app/services/agent_runner.py`) | `test_spend.py::TestBudgetGuard`, `test_agent_runner.py::…::test_a_failed_run_still_records_its_cost` |
| An approval is decided exactly once | `ApprovalService.decide` refuses a non-pending row read `for_update` (`app/services/approvals.py`) | `test_approvals_queue.py::TestDecidingTwiceIsRefused` |

### Confidentiality of credentials · HIPAA §164.312(a)(2)(iv)

| Control | Mechanism | Held by |
|---|---|---|
| No plaintext secret in any API response or audit entry | `SealedStr`/`CredentialStr` mask every repr; hints are last-4 only (`app/core/secret_kinds.py`, `app/core/vault.py`) | `test_no_secret_escapes.py` (sweeps the whole OpenAPI surface), `test_capability_secrets.py::TestInjection` |
| Logs are not part of that guarantee | A malformed MCP OAuth token response reaches the logs through a Pydantic `ValidationError` that echoes its input — a known gap, [#1626](https://github.com/vstorm-co/agenticos/issues/1626) | `test_mcp_connections.py::test_an_unreadable_token_response_does_not_echo_its_input` (documents that the token lands in `caplog`) |
| A credential is bound to its organization at rest | Per-owner HKDF envelope (`app/core/vault.py`); scope is connector and API credentials — see "What is encrypted where" for the bearer tokens it does not cover | `test_secret_tenant_isolation.py`, `test_vault.py` |

### Transmission security · HIPAA §164.312(e) · SOC 2 CC6

| Control | Mechanism | Held by |
|---|---|---|
| TLS to PostgreSQL and Redis | `POSTGRES_SSLMODE`, `REDIS_SSL` (`app/core/config.py`); `doctor` reports Postgres's live state from `pg_stat_ssl` | Postgres, on a live connection: `test_store_tls.py`; Redis, at URL construction and in `doctor`: `test_config.py`, `test_doctor_sandbox.py` |
| Framing and MIME headers on every response; CSP on all but the API-reference endpoints | `SecurityHeadersMiddleware` (`app/core/middleware.py`), whose `exclude_paths` drop CSP — not framing or MIME — for OpenAPI, Swagger and ReDoc; plus the frontend's per-deployment CSP (`frontend/src/middleware.ts`), whose `script-src` carries a per-request nonce and `'strict-dynamic'` rather than `'unsafe-inline'` | `test_security_headers.py`, incl. `test_an_excluded_path_keeps_its_framing_but_drops_the_csp`; `csp.test.ts`, `middleware.test.ts` |
| HTTPS and HSTS | Terminated at the reverse proxy — the bundled `nginx/nginx.conf` sets HSTS; the app does not, by design | Deployment concern; see the hardening checklist |
| Rate limits on public surfaces | Redis-backed limits on the run API, the embed widget and hosted pages (`app/services/rate_limit.py`); per-sender limits on channel bots (`app/services/channels/router.py`) | `test_rate_limited_surfaces.py`; the channel-bot limit is implemented but thinly tested |

### The refusals as a set

The refusal tests above carry the `security` marker. `make test-security` runs
the whole set, and CI publishes the collected list as a `security-tests.txt`
artifact on each backend run (#1417) — so the refusals can be counted and read,
not taken on trust. A test whose name or module mentions a tenant, a permission,
a budget, an approval, a secret or plaintext but lacks the marker fails
`tests/test_security_marker.py`, which keeps the list complete as the suite grows.

## Recap

- Trust the operator's infrastructure; trust no request into it. The boundaries
  that matter are browser → BFF → API → store, and API/worker → third parties.
  The BFF forwards the session cookie; the API is where a request is verified.
- The only data that leaves is what the deployment configured to leave — model
  providers, channels, MCP servers, search and embedding vendors, and Logfire —
  which is optional, and once a deployment-wide token is set traces every run,
  with the content of every agent that did not ask for `none`.
- Connector and API credentials are sealed per organization in the one vault;
  short-lived bearer tokens and content at rest (files, messages, RAG, sandboxes)
  are not, with [#1423](https://github.com/vstorm-co/agenticos/issues/1423) the
  app-level answer for object storage.
- Every control in the matrix names a mechanism and a test, and names its gaps in
  the same breath — tamper evidence and app-level file encryption each link the
  issue that would build them.
- Report vulnerabilities and run the hardening checklist from
  [`SECURITY.md`](https://github.com/vstorm-co/agenticos/blob/main/SECURITY.md);
  read [Data protection](data-protection.md) and [Licences](licenses.md) beside
  this page.
