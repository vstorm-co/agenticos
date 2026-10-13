# AgenticOS — delivery roadmap

The state of the platform and what is left, written so someone picking this up
cold knows both what exists and *why it was built that way*. Sections match the
board in the working plan (`VstormOS — MVP`).

Updated: 2026-08-27.

## Where the platform stands

| Area | State |
|---|---|
| Multi-tenant isolation | Done. Enforced in schema, repositories and services |
| RBAC | Done. Permission catalog in code, roles compose it, scopes on resources |
| Vault + model profiles | Done. Envelope encryption bound to the organization |
| Capability registry | Done. Code defines, configuration composes |
| Agent registry | Done. Draft → validate → publish → frozen version |
| Runs, budgets, approvals | Done, resume included |
| Skills and collections | Done, backend and UI |
| MCP | Catalog, per-user **and** org-scoped connections, agent bindings resolved at run time |
| Surfaces | Web chat, Playground, API, an embeddable widget, a raw WebSocket, a hosted page, Slack, Telegram and Mattermost — one run path, one set of books |
| Ingestion | Per-collection parser, chunking, OCR and image-description model; overridable per upload. Embedding model fixed at creation |
| Frontend | Agents, Builder, Skills, Sharing, Providers, MCP catalog, Activity, Roles, ingestion settings |
| Tests | Four layers plus Playwright. The platform layer is at **100%, enforced in CI**; the frontend gate is 100% lines/statements/functions and 97.5% branches |
| CI | Lint, types, tests, migrations forwards and back, frontend, E2E, security |

## Architecture, in the order it matters

**An agent is data.** `AgentSpec` is the contract — the Builder edits it, the
database versions it, a client commits it to their own repository as YAML.
`app/agents/factory.py` is the only place that turns it into something runnable.

**Capabilities, not tools.** A capability is the unit people decide about.
"Knowledge search" is one switch; whether it exposes one tool or three is an
implementation detail. Capabilities also cover things that are not tools —
budget enforcement, guardrails — so one concept covers the whole assembly.

**Code defines, configuration composes.** Configuration can only ever reach what
code registered. That is what makes a no-code Builder safe to hand to a client.

**Validate at publish, never at run time.** A broken agent is refused while
someone is looking at a form, not at 3am in a customer conversation.

**Every surface goes through one runner.** If each surface assembled its own
agent, budgets and history would hold whatever each one remembered to record.

## Delivered since the last revision

**R1 Skills UI, R4 approval resume, R7 onboarding** — done. **R2 MCP** — the
catalog is reachable (`/settings/mcp-servers`) and the orphaned per-user
connection manager is mounted at `/settings/integrations`; what is missing is
below as R8. **R3** — the agent page carries Build / Knowledge / Governance /
Sharing / Test / Activity; a public `/a/{slug}` link is below as R9.

**R5 channel `@mention` routing** — `app/services/channels/mentions.py`.
`@slug question` in Slack or Telegram runs that agent as *the sender*, with
their role in the bot's organization; an unlinked identity is refused rather
than run with no subject, and a slug resolves only inside the bot's
organization, so two workspaces can each have their own `@support`.

**R6 WebSocket chat on the factory** — done, and the product decision it was
blocked on is made: **the client names the agent; there is no per-organization
default.** A frame carrying `agent_id` runs that published agent through
`prepare()`/`finish()` stamped `RunSurface.WEB` — run history, cost, budget,
approval gate. A frame without one keeps the general assistant. Guessing a
default would mean a user asking one thing and something else answering.

**The BFF was missing entirely.** Every platform page called `/api/agents`,
`/api/skills`, `/api/runs`, `/api/approvals`, `/api/providers/*`,
`/api/me/permissions` — none of which had a Next route behind them. The pages
rendered and every query 404ed. Nothing caught it: unit tests mock the API
client and the E2E specs assert on headings and buttons, which render perfectly
well while the data layer fails. Replaced by one forwarder
(`frontend/src/lib/platform-proxy.ts`) that preserves the backend's status and
body, plus a test that reads the paths the hooks call and fails if any has no
route.

**The capability registry only loaded inside FastAPI.** `load_builtins()` ran in
the lifespan and nowhere else, so the CLI — including the documented
`make platform-bootstrap` — saw an empty registry and refused to publish any
agent, naming the capability as unknown. Lookups now load first.

**Per-collection ingestion, and three things it uncovered.** How a collection
parses, chunks and describes its documents is now stored on the row and
overridable per upload, with the embedding model fixed at creation because two
models of equal width write into different spaces that search goes on comparing.

Building it turned up that the machinery underneath was partly decorative:

- *LiteParse had never run.* `parse()` takes one argument and was being handed
  four keyword arguments; `page.pageNum` is the Node binding's spelling. The
  resulting `TypeError` fell outside the `except` clauses, so it surfaced as an
  unhandled worker crash rather than a parse failure. The parser was selectable
  in the UI and had never once executed. Same for the chat-attachment path,
  which called a `parse_async` method the binding does not define — and, being
  wrapped in `except Exception: return self._parse_pdf_pymupdf(data)`, had been
  silently using PyMuPDF all along. That path is now PyMuPDF and says so.
- *The advertised formats were fiction.* Three lists across two modules
  disagreed with what `process_file` could route, and the gap was an accepted
  upload — stored, committed, dispatched — that died in a worker.
  `tests/test_supported_formats.py` now pins them, and LiteParse genuinely
  reads its 40 formats (images natively, office via LibreOffice).
- *No environment left deciding.* `PDF_PARSER`, `RAG_CHUNK_SIZE`,
  `RAG_CHUNKING_STRATEGY`, `LITEPARSE_OCR_LANGUAGE` and five more are deleted.
  An installation-wide value made the same form produce different collections on
  two deployments with nothing in the product showing which. What stays in
  `Settings` is what a tenant must not choose: a key billed to the operator, an
  address on the internal network.

**The database image had no pgvector.** Every compose file and both CI jobs ran
`postgres:16-alpine`, so `CREATE EXTENSION IF NOT EXISTS vector` failed and the
first document upload into any collection 500ed before committing a row — which
means no ingestion path had ever been exercised locally or in CI, and an E2E
upload spec was sitting skipped because of it. Now `pgvector/pgvector:pg16`.
**Applying it locally needs the container recreated, which drops the dev volume.**

## Closed since that revision

**R12 the 100% gate** — restored, and `fail_under = 100` in
`backend/pyproject.toml` is what holds it. Adding a module to the platform layer
means editing two lists in that file, and `tests/test_coverage_gate.py` fails if
they drift.

**R8 organization-scoped MCP connections** — `scope`, `organization_id` and
`catalog_key` are written; `org_mcp_connections.py` and `me_mcp_connections.py`
are the two route modules, the org half gated on `connections:manage`, and a
binding resolves at run time. See
[MCP](mcp.md#personal-or-organization-wide).

**R9 a public agent link** — a [hosted page](channels.md#a-hosted-page) is one
kind of embed, served at `/e/{publicKey}`, with variables from the address bar and
a thread a visitor can come back to. It reuses the run path, so budgets and
history apply identically.

## Remaining work

### R10 — Python SDK and a versioning contract (board I1)
**Why:** the API is public from the first commit and has no client and no stated
compatibility promise.

### R11 — Logfire dashboard (board H4)
**Why:** `logfire_trace_id` is recorded on every run and still nothing reads it —
it reaches `frontend/src/types/runs.ts` and stops there.

## Testing

The bar and the layers are documented in [Testing](testing.md), and in
[`CLAUDE.md`](https://github.com/vstorm-co/agenticos/blob/main/CLAUDE.md#testing)
for anyone working in the repository.
!!! abstract "Short version"

    The platform layer is at 100% and CI enforces it; template-inherited
    subsystems are reported but do not gate the build, because mock-heavy tests
    over code we did not design buy a number rather than confidence.

What is worth testing here specifically — tenant isolation, permission scopes,
budget enforcement, spec validation, and that no response or log ever contains a
plaintext key — is listed in the same section.
