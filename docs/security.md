# Security

This page is what a HIPAA- or SOC 2-shaped security review hands over: the trust
boundaries, what data leaves the deployment and to whom, what is encrypted where,
and a controls matrix that names — for each control — the mechanism in this
codebase that satisfies it and the test that holds it true.

It describes what **is**, not what would be nice. A row with no mechanism says so,
and links the issue that would build it. For how to report a vulnerability and the
production hardening checklist, see [`SECURITY.md`](https://github.com/vstorm-co/agenticos/blob/main/SECURITY.md)
at the repository root; this page is everything else, in one copy.

## Threat model

The platform is self-hosted and multi-tenant. The design assumption is that the
operator's infrastructure is trusted and every request into it is not, so the
boundaries that matter are the ones a request crosses on its way to the data.

| Boundary | What crosses it | Trusted on the far side? |
|---|---|---|
| Browser → BFF (the Next.js route handlers) | A session cookie, the organization header, form input | No — the cookie is verified and every input validated |
| BFF → API (FastAPI) | A JWT bound to a DB session, the `X-Organization-Id` header | No — the token is verified per request and the org is resolved from it |
| API → PostgreSQL / Redis | Queries and cache reads, over TLS when configured | Yes — the store is the operator's, though it holds only sealed credentials |
| API / worker → model providers, MCP servers, search vendors, Logfire | Prompts, tool calls, queries, traces | No — these are third parties; what reaches them is a per-agent decision (below) |
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
| Logfire | Traces, which carry prompts and outputs by default | Only when an agent is given an observability token; the agent's `content` mode can reduce a span to timing and cost (`docs/reference/spec.md#observability`) |
| MCP servers | Tool calls and their arguments | Only for the tools an agent is bound to |
| A web-search vendor (Tavily, DuckDuckGo) | The search query | Only when the search capability is granted |
| An embedding provider | Document text, at ingestion | Only for a knowledge base whose provider is remote |

## What is encrypted where

There is one application-level encryption mechanism, and it is deliberately the
only one: the vault (`app/core/vault.py`). Every credential at rest is sealed in a
per-owner envelope whose wrapping key is derived, through HKDF, from the
organization (or user) it belongs to — so a ciphertext copied into another
organization's row fails to unwrap. The master key is rotatable without
re-encrypting the payloads.

Everything else at rest is the deployment's disk to encrypt, and this is stated
plainly because a review will find it:

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
| Permission on every collection route | `require(*perms)` route dependency (`app/api/deps.py`), catalog in `app/core/permissions.py` | `test_platform_routes.py::TestEachRouteDemandsItsOwnPermission`, `::TestEveryPlatformRouteIsGuarded` |
| A grant widens access without promoting the member | Per-resource `resolve_access` takes `max(role scope, grant)` (`app/services/access.py`) | `test_resource_access.py::TestGrantsWidenAccess`, `::TestPermissionsGrantsCannotWiden` |
| A channel mention runs as the sender, not the bot | A linked, active sender's own `AuthContext` is used (`app/services/channels/mentions.py`) | `test_channel_mentions.py::TestAnswer::test_the_run_carries_the_senders_own_role` |

### Authentication · HIPAA §164.312(d) · SOC 2 CC6

| Control | Mechanism | Held by |
|---|---|---|
| JWT (HS256), bcrypt passwords | `app/core/security.py` — `verify_token`, `get_password_hash` | `test_security.py`, `test_auth.py` |
| API keys compared in constant time | `secrets.compare_digest` (`app/api/deps.py`) | `test_auth.py`, webhook HMAC checks in the channel adapters |
| DB-backed sessions with revocation | `sessions` table + `SessionService`; token bound to a `sid` claim (`app/services/session.py`, `app/api/routes/v1/sessions.py`) | `test_session_verify.py`, `test_session_revocation.py` |
| Login rate limiting | `enforce_auth_limit` (`app/api/deps.py`) | `test_auth_rate_limit.py` |

### Audit controls · HIPAA §164.312(b) · SOC 2 CC7

| Control | Mechanism | Held by |
|---|---|---|
| Every gated mutation recorded, in the request's transaction | `record_audit` (`app/core/audit.py`), `app_admin_audit_logs` table | `test_skill_binding_audit.py`, `test_sync_source_audit.py` |
| The trail is readable by an auditor | `GET /audit`, gated on `audit:read` (`app/services/audit.py`) | `test_audit_service.py` |
| Exporting the trail (CSV/JSONL) | *Landing in* [#1422](https://github.com/vstorm-co/agenticos/issues/1422); run/approval/spend exports each write their own audit entry today | `test_run_export.py` (exports are audited) |
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
| No plaintext secret in any response, log or audit entry | `SealedStr`/`CredentialStr` mask every repr; hints are last-4 only (`app/core/secret_kinds.py`, `app/core/vault.py`) | `test_no_secret_escapes.py` (sweeps the whole OpenAPI surface), `test_capability_secrets.py::TestInjection` |
| A credential is bound to its organization at rest | Per-owner HKDF envelope (`app/core/vault.py`) | `test_secret_tenant_isolation.py`, `test_vault.py` |

### Transmission security · HIPAA §164.312(e) · SOC 2 CC6

| Control | Mechanism | Held by |
|---|---|---|
| TLS to PostgreSQL and Redis | `POSTGRES_SSLMODE`, `REDIS_SSL` (`app/core/config.py`); `doctor` reports the live state from `pg_stat_ssl` | `test_store_tls.py` |
| CSP, framing and MIME headers on every response | `SecurityHeadersMiddleware` (`app/core/middleware.py`) and the frontend's per-deployment CSP (`frontend/src/middleware.ts`) | `test_security_headers.py` |
| HTTPS and HSTS | Terminated at the reverse proxy — the bundled `nginx/nginx.conf` sets HSTS; the app does not, by design | Deployment concern; see the hardening checklist |
| Rate limits on public surfaces | Redis-backed limits on the run API, the embed widget and hosted pages (`app/services/rate_limit.py`); per-sender limits on channel bots (`app/services/channels/router.py`) | `test_rate_limited_surfaces.py`; the channel-bot limit is implemented but thinly tested |

## Recap

- Trust the operator's infrastructure; trust no request into it. The boundaries
  that matter are browser → BFF → API → store, and API/worker → third parties.
- The only data that leaves is what the deployment configured to leave — and an
  agent can trace without its prompts, or not at all.
- Credentials are sealed per organization in the one vault; content at rest
  (files, messages, RAG, sandboxes) is the deployment's disk to encrypt, with
  [#1423](https://github.com/vstorm-co/agenticos/issues/1423) the app-level answer
  for object storage.
- Every control in the matrix names a mechanism and a test; the three gaps —
  audit export, tamper evidence, app-level file encryption — each link an issue.
- Report vulnerabilities and run the hardening checklist from
  [`SECURITY.md`](https://github.com/vstorm-co/agenticos/blob/main/SECURITY.md).
