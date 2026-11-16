# Browser teaching and site procedural memory

**Status: backend and frontend implementation checkpoint; deployment disabled.**
The follow-up to issue #113 implements bounded hosted-browser capture, hosted
controls, owner capture discovery, explicit review, ordinary skill proposals,
bound-version discovery and optional member-approved task capture. Integrated
release CI, rendered desktop/mobile acceptance and deployment verification
remain release requirements. This document does not establish that the feature
is merged, deployed or available to users.

Baseline: T3OS `080c12941ed06cce2e92b6b03910e94ace36469e`, inspected on
14 November 2026. The product benchmark is
[OpenBot v0.71.0](https://github.com/nightly-labs/openbot/releases/tag/v0.71.0).
OpenBot's [release history](https://openbot.run/changelog) describes task teaching
and website learning. This proposal uses observed product behavior as a benchmark;
it does not copy OpenBot implementation.

## Problem and intended outcome

An operator can already let an agent use a managed browser, take over that
browser and keep a sign-in. They cannot demonstrate a repeatable task and save
the reviewed procedure as a skill. T3OS also has durable memory, but it does not
have an explicit, site-scoped library of navigation procedures learned from
those demonstrations.

Add **Teach a task** inside the provisioned browser panel. The operator performs
one task, reviews a redacted sequence, replaces case-specific values with
parameters and approves a skill proposal. A later agent run can retrieve the
approved procedure when it reaches an allowed origin. It still observes the live
page and follows the run's current permissions.

The first version works only in a T3OS-provisioned server browser. A user's
personal browser, browsing history and computer are outside this feature.

## Existing implementation to reuse

Paths in this table identify the integration boundaries checked for the original
design. The runtime checkpoint described below preserves those boundaries.

| Existing boundary | Integration decision |
|---|---|
| `backend/app/agents/capabilities/browser_use/_toolset.py`, `_direct.py`, `_loop.py` | Keep current browser tools, domain enforcement and step ceilings. A procedure supplies instructions; it cannot dispatch unchecked browser actions. |
| `backend/app/agents/capabilities/browser_use/_preview.py` and `backend/app/agents/browser_events.py` | Attach recording to the owned browser session and its human-control lease. Preview images remain ephemeral and are not teaching data. |
| `backend/app/agents/capabilities/browser_use/_native.py` | Explicitly refuse this surface for the first release. Native tab attachment is not a fallback. |
| `backend/app/services/browser_sign_in.py` and `browser_sign_in_session.py` | Preserve the existing person-scoped sign-in path. Authentication input and cookies never enter a demonstration. |
| `backend/app/services/skill_proposal.py`, `schemas/skill_proposal.py` | Reuse proposal review, final apply/discard decisions and skill version bumps. Add a typed teaching provenance field rather than calling the failure-learning endpoint. |
| `backend/app/services/auto_skill_learning.py` | Preserve failure-learning behavior. Browser teaching is a separate source of proposals, not a fabricated failure record. |
| `backend/app/services/memory/extraction.py` | Preserve the personal-memory extractor and its exclusion of quoted webpage/tool content. Site procedures do not enter personal facts or preferences. |
| `frontend/src/components/chat/browser-panel.tsx`, `browser-view.tsx` | Add Start, Pause, Stop, Discard and Review states to the hosted panel. |
| `frontend/src/components/skills/proposed-changes.tsx` | Show the new proposal's origin, parameters, source session and approval status. |

[PR #89](https://github.com/t3grp/agenticos/pull/89) supplies persistent hosted
workspace controls. Rebase the UI implementation onto its accepted result or an
equivalent reviewed launcher before connecting the teaching controls. This design
does not change that PR or rely on it being deployed.

## Operator flow

1. Open Browser and choose **Teach a task**. Show the task title, selected agent,
   target skill if any, allowed origins and the recording boundary.
2. Take human control using the existing browser lease. Recording starts only
   after the lease is confirmed for this member, organization and session.
3. Perform the task. A visible indicator remains present. Pause stops capture
   immediately; the operator can still use the browser.
4. Stop recording. No actions are replayed. Review the ordered structural steps
   and add a description for ambiguous controls.
5. Define parameters such as `invoice_number` and `report_month`. Typed form
   values are not recovered from the recording.
6. Request a draft procedure from the reviewed, bounded sequence. This is the
   first optional model call and uses an explicit budget.
7. Review and apply the skill proposal. Binding a new skill to an agent still
   requires the existing draft and publish flow.
8. On a later visit, the agent may discover the approved procedure. It reads the
   live page before acting and reports when the procedure no longer fits.

A demonstration can make real changes to the external application because the
operator is using that application. The recording controls must not suggest a
sandboxed rehearsal or automatically repeat a demonstrated submission.

## Capture contract

Capture structured actions at the owned browser input boundary. Do not collect
the operating system's input stream or attach a second browser listener to
unrelated tabs. Browser ownership and the human-control lease are checked before
every accepted event.

Allowed event types are `navigate`, `click`, `select`, `input_parameter`,
`scroll` and `checkpoint`. The first implementation records no screenshots,
video, network bodies, raw HTML, scripts, cookies, local storage, clipboard
content or typed values. Authentication and CAPTCHA interactions are omitted
and represented only by an explicit human step.

A target stores its role and a structural fingerprint. DOM text, accessible
names, input names and attribute values are not persisted automatically. The
reviewer supplies a safe descriptive label; a future label suggestion feature
requires a separate capture review. This deliberately makes privacy independent
of a model deciding whether a page contains a secret.

Navigation stores an exact origin. Paths begin as structural placeholders and
become reusable templates only after review. Query strings, fragments, userinfo
and token-bearing URL parts never enter the stored event. Only HTTPS origins
without wildcards are accepted initially.

Persisted event example, using synthetic data. The input identity and sequence
are minted by the owning server pipeline; a browser client cannot submit them:

```json
{
  "sequence": 4,
  "input_id": "8fb87bfd-3527-5d25-80ab-c4f3e2f8539c",
  "action": "input_parameter",
  "origin": "https://portal.example.test",
  "target": {
    "role": "textbox",
    "fingerprint": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  },
  "direction": null,
  "human_step": false
}
```

Reviewed labels, parameter names and path templates are supplied separately by
the person reviewing the ordered sequence. No `value` field is accepted, even
when it is null. The server rejects unknown fields and repeated input identities
with different payloads. Repeating an identical event is idempotent. Limits are 500 events,
128 KiB of sanitized events and 30 minutes per session. Exceeding a limit pauses
capture with a visible reason; it does not silently truncate a procedure.

## Runtime persistence and states

The dedicated `browser_teaching_sessions` row records:
`id`, `organization_id`, `owner_user_id`, `agent_id`, `run_id`,
`controller_id`, `connection_id`, `takeover_id`, `call_id`, `tab_id`,
`target_skill_id`, `allowed_origins`, `source`, `status`, `revision`,
`sanitized_events`, `review`, `procedure`, `source_hash`, `policy_generation`,
`preference_generation`, `generation_state`, `proposal_id`, `created_at`,
`capture_ends_at` and `expires_at`, with additional exact generation-claim fields.

The browser identities are references, not CDP endpoints or credentials.
The row records authority and provenance; it does not own a second browser.
Migration `0335_browser_teaching` follows the real
`0334_workflow_media_operations` revision. The feature branch and core migration
head remain separate until the release's explicit merge revision; neither
published history nor the predecessor is renamed or replaced.

| State | Allowed next states | Effect |
|---|---|---|
| `recording` | `paused`, `review`, `discarded`, `expired` | Accept bounded events while the lease is valid. |
| `paused` | `recording`, `review`, `discarded`, `expired` | Accept no events. Resume requires a fresh ownership check. |
| `review` | `proposed`, `discarded`, `expired` | Edit redacted steps and parameters; capture is closed. |
| `proposed` | terminal | Link the proposal; its existing apply/discard lifecycle is authoritative. |
| `discarded`, `expired` | terminal | Remove event payloads and retain minimal audit metadata. |

Abandoned or unproposed sessions expire after 24 hours. Applied or discarded
proposals retain reviewed procedure text through the existing proposal policy;
their transient event payloads are erased. Expiry and erase jobs use the durable
background queue. A missed job must be retriable without reviving recording.

## Runtime API

All responses contain sanitized procedure metadata only. Routes call a teaching
service, which coordinates repositories and browser ownership checks.

| Route | Contract |
|---|---|
| `POST /v1/browser-teachings` | Start a new-skill candidate. Collection gate uses `skills:edit`; service also requires current permission to use the agent and own the browser lease. The client-generated `request_id` identifies one exact start intent. |
| `POST /v1/skills/{skill_id}/browser-teachings` | Start a candidate for an existing skill. The service resolves `skills:edit` on that exact skill, including grants; no broad role gate overrides the grant. |
| `GET /v1/browser-teachings` | Discover the current personal owner's captures in the active organization using bounded, newest-first cursor pages. The response contains only closed summary metadata. |
| `GET /v1/browser-teachings/{id}` | Owner-only metadata and review payload, scoped to the current organization. |
| `PATCH /v1/browser-teachings/{id}` | Pause/resume or edit review fields using `If-Match` and the current revision. |
| `POST /v1/browser-teachings/{id}/stop` | Atomically stop capture and enter review. Repeated stop returns the same review state. |
| `POST /v1/browser-teachings/{id}/propose` | Validate reviewed content, check current authority and budget, then enqueue one proposal build. Same source hash produces one proposal. |
| `DELETE /v1/browser-teachings/{id}` | Discard an unproposed session and erase payloads. This does not undo browser actions or delete an already applied skill. |
| `GET`, `PUT /v1/browser-teaching-policy` | Read the organization opt-in and deployment admission; changing it requires current `org:settings` and the exact policy generation. |
| `GET`, `PUT /v1/agents/{agent_id}/browser-teaching-preference` | Read or change the acting member's opt-in for this agent using its exact generation. A known choice can still be revoked after agent access is lost. |

No public route accepts arbitrary recorder events. Only the server-owned input
pipeline can append them. Requests with stale revisions return `409`; exhausted
capture limits return a stable reason code and the paused state. An inaccessible
row is indistinguishable from a missing row.

Proposal generation is a durable job keyed by session id, revision, source hash
and claim token, with one attempt. If current authority changes while queued or
before a model request or final write, the job refuses. An unknown attempt is
terminal and is never automatically retried. Reading the session reconciles its
status; another attempt requires a new explicit capture/review flow. The default
`reviewed` mode renders the reviewed procedure without a model. Optional
`assistant` mode requires an explicit positive budget of at most USD 10, checked
before queuing. The model sees reviewed steps and parameter names, never browser
session state. All metadata responses use `Cache-Control: no-store`; session
responses carry an `ETag` matching the revision used by `If-Match` mutations.

### Finding captures after a browser session ends

The collection read lets an owner recover a manual capture or a task refinement
when its browser event was missed or the browser panel is no longer open. Every
page refreshes the same personal-user and active-membership authority as the
per-ID read, then scopes the database query to both owner and organization.
API keys, impersonation and publisher stand-ins cannot use it. An organization
administrator does not gain another person's captures through their role.

Owner recovery remains available after teaching is disabled, the live tab ends,
or the owner loses skill-edit permission. This read grants no new capture,
generation, execution, proposal or skill-application authority. Review and
effects always use the existing per-ID routes and their current checks.

`TeachingList` returns only `items` and nullable `next_cursor`. Each
`TeachingSummary` contains `id`, `agent_id`, nullable `target_skill_id`, `title`,
`allowed_origins`, `source`, `verified_success`, `status`, `revision`, nullable
`reason_code`, `generation_state`, nullable `proposal_id`, `created_at`,
`expires_at` and `capture_ends_at`. The query does not load captured actions,
reviewed procedures, browser/run identities, lease or generation tokens, or
budgets. The response is not cached.

`limit` defaults to 20 and accepts 1 through 100. Pages use
`created_at DESC, id DESC` keyset ordering and have no status filter. The opaque
cursor is bound to its owner and organization, so clients reset it on either
audience change. Invalid, unsupported or cross-audience cursors return `400`
`BAD_REQUEST` with `details.reason_code=invalid_cursor` and a `cursor` field
problem, without echoing the token. Restart without the cursor. An oversized
cursor or out-of-range page size returns `422`.

Listing is read-only. At the existing retention boundary, recording, paused and
review summaries project the same expiry as the canonical owner read: title and
origins are erased, status and reason become expired, revision advances once,
and queued or generating work appears cancelled. The list does not mutate the
capture or run background work. Terminal and proposed states retain the
canonical read's semantics; ordinary retention and proposal decisions still own
their erasure. A client must reopen the capture before reviewing or acting.

## Site procedural memory

Implement site memory as **approved procedure metadata attached to a skill
version**, not as unreviewed website text or a new general personal-memory store.
Suggested `browser_procedure` metadata has a schema version, exact origins,
reviewed path templates, parameter schema, prerequisites, success checks, source
session id and source hash.

Discovery requires access to the published agent's bound skill and a matching
origin. There is no organization-wide automatic injection of another person's
procedure. A skill's existing visibility and resource grants govern its review
and editing; binding follows existing publish validation.

The optional **Learn procedures from this browser** setting is off initially.
When enabled for an agent and member, completed managed-browser work may propose
a refinement using the same redacted contract. It cannot publish, widen origins,
alter permissions or overwrite approved content. User and organization opt-outs
both win, and switching it off cancels pending capture and generation.

The runtime distinguishes two sources. Manual teaching requires the exact live
human takeover and always records `verified_success=false`. Optional task capture
requires deployment admission, organization policy, the current published agent's
capture and learning settings, and the acting member's explicit per-agent choice.
It records only the owning run's accepted native actions, without inventing a
human connection or takeover. A successful browse leaves a suggestion awaiting
the final run outcome. Only an actual completed run can set `verified_success`;
failed, cancelled, revoked or incomplete work is erased. This flag describes
browser/run completion evidence, not independent verification of the website's
business result. Both sources still require human review and the existing
apply/discard decision. Neither source publishes or binds a skill automatically.

A procedure supplies expected steps and success checks, never stored DOM ids
for blind playback. Re-observe each page, rematch the intended control and stop
when the observed state differs. A failed procedure may create a review
suggestion; it cannot turn hostile page instructions into a standing skill.

## Authority and tenant boundaries

Every transition checks current membership, organization, owning person,
agent-run authority and browser ownership. Editors of a skill do not
automatically gain access to another person's unfinished recording. Recording
is unavailable to anonymous embeds, API keys without a human subject, public
shares, channel outsiders, delegated runs and impersonation contexts initially.

Organization and person ids come from authenticated context, not request fields.
Revocation, account switching and organization switching immediately stop capture.
The frontend clears review state and pending requests on each identity change.
An in-flight model result must recheck authority before it creates a proposal.

Do not reuse a remembered browser login as permission to teach or share a skill.
Publishing a procedure shares only reviewed instructions, never the recorded
person's access to the target website.

## Implementation sequence and acceptance

| Slice | Reviewable result | Required acceptance evidence |
|---|---|---|
| 1. Contracts and privacy boundary | Models, typed schemas, recorder validation and retention worker, behind a disabled deployment flag | Synthetic secrets, cookies, URL tokens, OTP inputs and arbitrary DOM text are absent from rows, logs, traces and errors; cross-tenant requests fail. |
| 2. Hosted browser capture | Lease-bound recording with pause, stop, discard and limits | Two users and two tabs cannot cross-record; takeover loss and disconnect stop capture; repeated events cannot duplicate steps. |
| 3. Review and proposal | Parameter review, one bounded proposal job and existing apply/discard UI | Budget refusal makes no model call; permission loss before job completion refuses writes; repeated generation yields one proposal; stale edits conflict. |
| 4. Procedure discovery | Approved, bound, origin-scoped procedures supplied to managed browsing | An unrelated origin, unbound skill, unpublished change or inaccessible skill is never returned; changed DOM requires fresh observation. |
| 5. Opt-in refinements | Explicit per-member and per-agent preference and review-only suggestions | Opt-out cancels pending work; web text cannot auto-publish; failed runs cannot claim successful verification. |

Browser tests must use synthetic local applications with known labels and seeded
data. Cover a real demonstration, pause around sign-in, parameter review, apply,
publication and one later execution. Verify event payloads as well as the UI.
Do not run real client workflows to establish these guarantees.

Before enabling: complete PR #89 integration, relevant backend/frontend/browser
tests, privacy tests and the normal release gates. Update published browser and
skills documentation, onboarding, permission-sensitive controls and translations
in the implementation PR. This repository-only design remains excluded from the
published documentation site.

## Backend checkpoint and remaining acceptance

The backend implementation is in `app/core/browser_teaching.py`,
`app/db/models/browser_teaching.py`, `app/repositories/browser_teaching.py`,
`app/schemas/browser_teaching.py`, `app/services/browser_teaching/`, and
`app/api/routes/v1/browser_teaching.py`. The existing browser capability owns its
recorder through `_teaching_hooks.py` and `_teaching_page.py`; the ordinary input
and task loops remain the only browser writers. `SystemAgentRunner` accepts a
scoped authority callback before each optional draft-model request. Existing
skill-proposal apply/discard and version creation preserve the reviewed source
provenance, and ordinary edits clear browser-procedure metadata instead of
claiming the original capture still verifies changed instructions.

The takeover WebSocket mints the connection identity and monotonically stamps
accepted input messages. `browser_held.takeover_id` is the opaque token required
to start or resume manual capture. `browser_teaching` events carry only
`teaching_session_id`, `teaching_status`, `teaching_revision` and a fixed
`teaching_reason` alongside the existing run/call/tab address. A different
connection, controller, member, organization or resumed process cannot append to
the old recording. Losing the lease pauses manual capture; resuming requires
fresh live authority. One person may hold at most 20 outstanding recordings or
reviews. The server bounds the lease and native observation requests, checks
document identity around structural capture, and refuses unbounded/authentication
forms as value-free human checkpoints.

Credential protection takes precedence over both recording modes. Capture stops
before protected credential delivery, and neither later navigation nor stale
frames can restore recorder access to that protected page. The existing sticky
browser output guard remains authoritative. Teaching does not weaken the
credential feature's separate confirmation, submission or human-handoff flow.

Native acceptance uses one disposable, sandboxed Chromium process and exact
synthetic HTTPS pages fulfilled locally. It exercises a real manual
demonstration, value-free parameter review, deterministic draft, explicit apply,
agent publication, later procedure discovery and fresh-DOM action refusal. It
also covers opt-in task capture, password/OTP/CAPTCHA/frame/form bounds and the
protected-output stop. No live client workflow or paid provider is used. Native
PostgreSQL tests cover the real predecessor graph, up/down model parity,
unchanged legacy skill data, interrupted concurrent-index recovery, refusal to
replace a conflicting index, and refusal to downgrade populated teaching data.

## Frontend controls and review

The shared browser window exposes **Teach a browser procedure** for an addressed,
unprotected live view. Opening it reads the organization policy and that run's
authorized agent metadata. Recording is available only to the current holder
with the current server-issued takeover token; reconnecting without a fresh
browser_held token does not reconstruct permission. The form identifies exact
HTTPS origins and explains that clicks and navigation affect the live website.
It offers a new skill where the person may create one, or an existing editable
skill selected through the ordinary per-resource authority.

Pause, Resume and Stop recording use the persisted capture and its current
revision. Resume additionally requires the current takeover token and an
unexpired capture window. Stopping recording opens the review stage; it does not
stop the hosted browser run. Protected credential output removes teaching
controls and cached takeover state immediately, including after a reconnect or
late browser event. It cannot be reversed by later raw frames or navigation.

**Skills → Browser teaching** lists the current person's captures from the
paginated owner/org collection at /skills/teaching. Opening a row reads its
exact current receipt at /skills/teaching/{id} before exposing review or
decisions. The list distinguishes expired captures, manual demonstrations and
suggestions from completed work. A refused fresh read hides retained private
metadata, including a membership refusal; an invalid cursor offers a fresh
first page rather than silently mixing pages.

The review editor preserves every captured sequence in order. The person
supplies step labels, parameter names and descriptions, explicit relative path
templates, prerequisites and success checks. Omitting a step is an explicit
choice. No captured value, parameter default, page label or selector is
reconstructed. A newer server revision requires reloading the review before
saving. A refused generation must be reviewed and saved again before another
draft is offered.

The default **Create draft from reviewed steps** path makes no model call.
Assistant drafting is a separate choice with an explicit positive USD ceiling,
bounded by the backend's ten-dollar limit. Neither path applies the draft.
The handoff uses the existing Skills proposal review: a new skill has its
separate Apply/Discard decision, and an existing skill retains the agent-check
flow. The handoff is withheld when the person lacks its existing permissions.
Applied browser-procedure provenance is displayed only on the exact teaching
version. Ordinary edits and restores do not inherit that provenance. Manual
capture and the completion-state flag never claim independent verification of
the website's business result.

Start and Draft retain the exact scoped request tuple before a write. An
uncertain response survives reload and a later read refusal. **Check again**
performs only GET recovery; only an explicit retry button may send the same
retained tuple again. Delayed responses are rejected after an actor or
organization change. Cached reads poll for at most three minutes at a time,
with an explicit GET-only check after that window. Local expiry displays remain
current without extending network polling or starting another model job.

An acknowledged newer saved review may retire only the same retained Draft
tuple: the backend serializes review and generation admission on the capture
row. A lost review acknowledgment, changed audience or different retained tuple
cannot settle the old attempt. Saving a review never starts another Draft, and
retiring an older refused attempt does not establish that it incurred no cost.

Organization governance contains the default-off teaching policy with a
generation-checked confirmation. Acting-member learning preferences are scoped
to that exact run's agent, remain off by default, and allow a known enabled
preference to be revoked after agent access is lost. Capability settings expose
the separate allow_teaching and learn_site_procedures options. Policy, frozen
capability configuration, the current person and live controller remain
authoritative; the frontend never enables deployment admission.

The English message catalog, existing locale fallback and onboarding help cover
the new settings, live controls, review and separate draft/publication decisions.
The review guide does not click consent or publication actions.

### Frontend acceptance boundaries

Scoped tests exercise tenant changes, current takeover tokens, protected output,
complete ordered review, revision conflicts, uncertain request recovery, default
no-model drafting, explicit budgets and existing proposal authority. Synthetic
desktop and mobile cases in
frontend/e2e/browser-teaching-visual-fixtures.spec.ts use the actual Skills,
review, hosted-browser and organization-settings routes. They first check real
owner authentication and the native read contracts, then substitute clearly
labelled capture metadata and socket events. Their screenshots are fixture-only
evidence; they do not prove a live website flow or paid provider execution.

Full integrated release CI, review of the rendered desktop/mobile evidence and a
deployed synthetic flow remain required before changing availability
documentation or enabling the organization allowlist.

## Rollout and rollback

Enable the first slice only for a test organization with synthetic accounts.
Then enable manual teaching for selected agents; automatic refinements remain
off until the first flow has evidence. Record counts and reason codes for
started, paused, discarded, expired and proposed sessions. Never attach payloads
or URLs with parameters to telemetry.

A disabled feature flag blocks creation, append and generation immediately and
cancels pending jobs. Existing approved skills remain ordinary skills; removing
their bindings uses the normal publish flow. Retention and erase workers continue
while the feature is disabled. Rollback never replays a demonstration or removes
a person's existing browser sign-ins.
