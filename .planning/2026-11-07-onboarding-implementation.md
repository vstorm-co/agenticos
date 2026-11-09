# Unified onboarding — implementation and verification map

Base: `0306cad25cb56a443487101aef285a6c00f95fef` (1.55.0).
Branch: `codex/unified-onboarding`; isolated worktree: `agenticos-unified-onboarding`.

## Contracts

- Existing shipped-agent synchronization remains authoritative. An explicit, idempotent preparation action can create a text-only assistant on a deliberately selected shared model; it does not change an existing draft or spend provider tokens.
- `GET/PATCH /me/onboarding` is scoped to the authenticated person and active membership. Goals and dismissal are stored on membership, not account or shared browser storage. Dismissal and demonstrations never manufacture successful runs.
- A completed personal web run with a surviving owned conversation is evidence of execution. This is not a claim that the user found its answer useful. Live ACL and published status are separate from actual provider availability; the explicit first task verifies the latter.
- Native setup prepares the environment. The common web start handles product activation. Desktop features remain optional; device grants are not required for a text task.
- No provider/model upgrade, paid trial, global telemetry service, automatic integration, or recurring work is added.

## Scenario traceability

| Audit scenarios | Delivery surface |
|---|---|
| 1–4: operator, browser owner, nontechnical local/desktop | Common start hub; existing bootstrap/runtime retained; explicit minimal starter and model configuration; native language choice and fewer required fields. |
| 5–9: invitations, second organization, SSO, restricted members, remote desktop | Invitation immediately opens the shared hub in the joined organization; start state follows membership; actual per-resource run grants; no model/agent creation for unauthorized members; optional device setup; explicitly pasted native invitation links retain their same-server destination through sign-in. Existing SSO admission and organization recovery remain in use. |
| 10–12: no model, invalid model, no agent | Recorded examples without provider calls; integrated model picker and normal publish validation; charged task is explicit; standard runner errors remain authoritative. |
| 13–15: documents, team rollout, creating an agent | Inline fictional policy needs no ingestion. Own-file, agent builder, personal account and team entry points reuse existing product workflows. Loopback invite warning and team-readiness guidance. |
| 16–19: interruption, return, access loss, mobile | Server-stored goal/dismissal and latest real result; retry/error states; organization recovery; no forced full tour; responsive shared hub; existing device-specific mobile setup remains optional. |
| 20–25: routines, repair, approvals, integrations, artifacts, local AI | Existing permission-gated routines, approvals, OAuth return and artifact viewers remain in place; hub links to optional next actions and saved conversation. Local lifecycle/privacy and reachable-server guidance are explicit. |

The table maps new work and existing behavior. It does not certify clean-machine installation, real provider availability, cross-platform native signing, or user comprehension. Those require their corresponding runtime/CI checks and observed sessions.

## Verification

Results are recorded below as checks complete. Full laptop suites are intentionally not run; CI owns their coverage and build gates. The new PostgreSQL constraint and migration need a live pgvector-enabled test database.

### Completed locally

- Backend: 31 focused tests passed (21 onboarding service/API tests plus 10 coverage-contract tests). The four new platform modules reach 100% statement and branch coverage in the focused `--cov=app` run.
- Frontend: 105 focused tests passed across 17 files, including account creation, invitations, opt-in tours, examples, tenant-scoped cache and native language. Another 36 existing-feature tests pass for the desktop gate/welcome, page help and invitation dialogs. The final focused rerun also covers recorded-example return, read-only material and quiet start offers without interrupting chats. The new start hook and API/local-address helpers reach 100% coverage in their focused run.
- Backend lint, type checking, dependency and documentation guards pass. The frontend production build passes. Documentation builds with `mkdocs --strict` in all four site languages. Existing release-note links to a removed Prefect heading remain informational build notices.
- Native: `cargo fmt --check`, `cargo check --locked` and the focused `onboarding_language_tests` (including invitation continuation/refusal) pass on this macOS host.
- Inspected isolated browser renders with fictional data: available agent, no agent, recorded demonstration, mobile hub, and native Polish server selection. No real provider calls or user data were used.

### Runtime acceptance still needed

- Docker is not running on this host. The two real-PostgreSQL membership/constraint tests skip locally; migration upgrade/downgrade and `alembic check` must pass in CI against pgvector PostgreSQL.
- Clean-machine installation, native OS prompts/signing on other platforms, real provider failure/recovery and full invitation/SSO journeys require runtime acceptance. Unit tests and screenshots do not certify these.
- The audit's observed usability sessions, activation funnel measurements and time-to-value targets remain validation work. No synthetic success, recorded demonstration or closed tour is counted as an actual completed task. This change derives execution evidence from existing completed runs and does not add a new analytics collector.

## UI refinement

The start keeps the console's existing neutral palette, typography and deployment branding. Task-specific SVG paper illustrations, contextual icons, a stronger heading, a suggested primary action, rounded panels and responsive card layouts make the first choice easier to scan. Explicit recorded previews receive heading focus after opening; their labels still distinguish them from real execution.

Entry animations and hover illustration movement use the shared MotionProvider's resolved preference. The reduced state has no entry or travel animation. Browser verification checks both reduced motion and enabled hover movement. The small-phone layout changes at 360px so translated actions remain usable.

Inspected isolated renders: ready, returning, owner without an agent, member without an agent, recorded example, light/dark, Polish at 390px and German at 320px. No page errors or horizontal overflow appeared. Sixty focused tests pass, including the CI-discovered loading-shape guard and updated native startup/readiness tests. Frontend lint, type/i18n/dependency checks and the production build pass; the full CI rerun belongs to the pushed refinement commit.

## Resilience and navigation iteration

- Recorded previews open immediately, independently of the preference write. Pending actions are announced; their buttons describe the corresponding task. Back returns focus to the source button, or its heading while the write is pending. Leaving the page prevents a delayed save from navigating back to chat.
- The persisted-choice message names the task actually saved. A failed new choice is never presented as a newly saved result.
- Preference and preparation mutations retain the initiating user/organization cache key. Changing scope resets their visible mutation state rather than carrying an old pending/error state into the next workspace.
- The dashboard's start panel reserves its final dimensions while loading and provides retry on read failure. Isolated renders of the actual opening components measured identical bounds before/after load: 564 × 496 at 1440px and 342 × 224 at 390px, with no horizontal overflow or page errors.
- CI for `4cd244384` exposed a missing proxy-route coverage registration, the old dashboard-checklist e2e contract, stale generated Architect help and the missing update-schema target registration. These are corrected without lowering gates. The backend run reached 100% platform coverage with 29,371 tests passing and two guard failures; the corrected guard/schema/onboarding batch passes locally (73 passed, 11 schema-parameter skips). The focused frontend scope/proxy suite passes 119 tests and measures 100% coverage for both affected modules. The updated real-stack dashboard journey remains for the new CI run.
