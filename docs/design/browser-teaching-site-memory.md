# Browser teaching and site procedural memory

**Status: proposal only.** This design adds no recording, model call, route,
database table or browser permission. The APIs and schemas below are proposed
contracts for implementation PRs. Do not list the feature as available after
merging this document.

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

Paths in this table were checked at the baseline commit. The additions below are
new work; the listed modules already exist.

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

Proposed bounded event example, using synthetic data:

```json
{
  "sequence": 4,
  "action": "input_parameter",
  "origin": "https://portal.example.test",
  "target_role": "textbox",
  "target_fingerprint": "sha256:synthetic-structure-fingerprint",
  "reviewed_label": "Invoice number",
  "parameter": "invoice_number",
  "value": null
}
```

The server rejects unknown fields and duplicate sequence numbers with different
payloads. Repeating an identical event is idempotent. Limits start at 500 events,
128 KiB of sanitized events and 30 minutes per session. Exceeding a limit pauses
capture with a visible reason; it does not silently truncate a procedure.

## Proposed persistence and states

Use a dedicated `browser_teaching_sessions` row. Suggested fields are:
`id`, `organization_id`, `owner_user_id`, `agent_id`, `run_id`,
`browser_session_id`, `target_skill_id`, `allowed_origins`, `status`,
`revision`, `sanitized_events`, `parameters`, `source_hash`,
`proposal_id`, `created_at` and `expires_at`.

The browser session identifier is a reference, not a CDP endpoint or credential.
The row records authority and provenance; it does not own a second browser.
No migration number is reserved in this design.

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

## Proposed API

All responses contain sanitized procedure metadata only. Routes call a teaching
service, which coordinates repositories and browser ownership checks.

| Proposed route | Contract |
|---|---|
| `POST /v1/browser-teachings` | Start a new-skill candidate. Collection gate uses `skills:edit`; service also requires current permission to use the agent and own the browser lease. Accept an idempotency key. |
| `POST /v1/skills/{skill_id}/browser-teachings` | Start a candidate for an existing skill. The service resolves `skills:edit` on that exact skill, including grants; no broad role gate overrides the grant. |
| `GET /v1/browser-teachings/{id}` | Owner-only metadata and review payload, scoped to the current organization. |
| `PATCH /v1/browser-teachings/{id}` | Pause/resume or edit review fields using `If-Match` and the current revision. |
| `POST /v1/browser-teachings/{id}/stop` | Atomically stop capture and enter review. Repeated stop returns the same review state. |
| `POST /v1/browser-teachings/{id}/propose` | Validate reviewed content, check current authority and budget, then enqueue one proposal build. Same source hash produces one proposal. |
| `DELETE /v1/browser-teachings/{id}` | Discard an unproposed session and erase payloads. This does not undo browser actions or delete an already applied skill. |

No public route accepts arbitrary recorder events. Only the server-owned input
pipeline can append them. Requests with stale revisions return `409`; exhausted
capture limits return a stable reason code and the paused state. An inaccessible
row is indistinguishable from a missing row.

Proposal generation is a durable job keyed by session id, revision and source
hash. If permission or ownership changes while queued, the job refuses. If its
outcome is unknown, reconcile by its key before retrying. The model sees only
reviewed steps and parameter names, never browser session state.

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
