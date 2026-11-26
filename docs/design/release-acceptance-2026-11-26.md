# AgenticOS release train: acceptance review

Prepared 26 November 2026 for [aggregate PR #3455](https://github.com/vstorm-co/agenticos/pull/3455). This is a review and acceptance document, not a release announcement. The selected changes are assembled for testing on one checkout. **Merge, version publication and production deployment are not authorized.**

The practical result is a more configurable console, portable agents/workflows with reviewed dependencies, separate project files and execution targets, reusable event sources, and tighter approval/Improve behavior. The tables below identify each selected source rather than treating successful source CI as proof that the combined train passes.

## Selected source pull requests

| Source | What changes for a member or operator | Where it appears | Material review/integration correction | Limits and acceptance points |
| --- | --- | --- | --- | --- |
| [#3299](https://github.com/vstorm-co/agenticos/pull/3299) | Export agents and workflows with selected dependencies; import by creating private copies, reusing authorized resources or omitting them. ZIP can carry Context/Skill files and knowledge originals/parsed snapshots. Project context and command execution can be selected separately. | Agent/workflow export and import dialogs; project pages and chat settings; Chat Files origin picker; KB document status/preview. | Schema-owned reference mapping replaces raw-ID copying. Exact versions and table schemas are remapped together. Durable transfers reauthorize, fence writes, preserve idempotent receipts and clean abandoned storage. Project/delegate selections preserve audience, generation and executor guards through continuations. | Imports do not publish, run or embed. KB vectors/indexes are excluded; imports say **stored/unindexed**. Parsed-only content can be previewed but requires an original before indexing. Secrets are not transferable. No silent file copy or same-path fallback between Agent and Project origins. Historical runs do not gain invented origins. [R1–R3] |
| [#3388](https://github.com/vstorm-co/agenticos/pull/3388) | Full-screen panels keep controls clear of device status bars and home indicators. | Files, Sources, browser, builder test panel, tables, datasets, workflows, sandbox and other expanded panels. | Replaced five template-literal class expressions with the established class helper so the i18n guard stays effective. | Responsive/browser evidence does not establish native-device coverage for every panel. [R4] |
| [#3383](https://github.com/vstorm-co/agenticos/pull/3383) | Recover the saved answer after a dropped chat socket, or resume following a still-running turn, without duplicate rendering or a stuck interruption notice. | Chat messages, reconnection notice and “Check for it”. | Snapshot saved segment IDs at connection loss. An older question segment or another detached run cannot masquerade as the missing continuation. | Recovery still depends on a persisted answer or a reachable live run; it does not invent output. Also addresses #3382. [R4] |
| [#3304](https://github.com/vstorm-co/agenticos/pull/3304) | API clients can submit a correction by conversation ID with `steer: true`; a running attempt consumes it before a later model call, or it becomes a normally admitted next turn. | HTTP async-run API; no new console layout. | Preserved the queue lease fence and exact agent/environment/person/credential identity. Consumed requests retain a terminal receipt referencing the original run. | Opt-in; requires an existing API conversation. It cannot interrupt an already running provider call or switch that attempt's executor. Rejected/stale steering remains queued for normal admission. [R4] |
| [#3448](https://github.com/vstorm-co/agenticos/pull/3448) | Approval cards name the relevant agent, Skill, dataset, version, attempt or result instead of relying on IDs alone. | Live chat approval dialog and approval/activity cards. | Resolve descriptions under the run person's access checks; validate IDs and nested arguments. Only server-proven platform provenance can receive trusted platform context. | Enrichment is optional. Missing or inaccessible descriptions retain the original arguments; this never authorizes a decision. [R5] |
| [#3447](https://github.com/vstorm-co/agenticos/pull/3447) | Pressing Stop as a response finishes cannot accidentally send the next draft. Keyboard focus follows the intended Send→Stop transition. | Both chat composer layouts, desktop and mobile. | Reviewed the later ready source head, including its focus correction; retained distinct DOM identities and draft/focus regressions. | Deterministic real-component interaction was tested, not a paid provider conversation. The earlier draft snapshot was not silently accepted. [R6] |
| [#3446](https://github.com/vstorm-co/agenticos/pull/3446) | Improve sessions keep their original holdout share across attempts; Skill test sets keep all questions held out. | Improve measurement behavior; no layout change. | Persist the already prepared input snapshot rather than rereading a concurrently changed/deleted dataset. | Historical sessions must be backfilled from the dataset's current value, or 0.5 when orphaned; the historical original was never stored. Skill repairs intentionally survive downgrade. [R7] |
| [#3445](https://github.com/vstorm-co/agenticos/pull/3445) | Proposed capability changes show their full binding and warn about invisible/control or text-reordering characters. | Authoring/Improve diff and structured field-change views. | Inspect structured keys and values before JSON serialization; render added/removed binding bodies; cover astral Unicode format characters. | The warning makes hidden content inspectable; it is not a claim to prevent every deceptive instruction. [R7] |
| [#3444](https://github.com/vstorm-co/agenticos/pull/3444) | Paid starts carry a quoted estimate and relevant version pins; stale approved estimates can be refused before work begins. | Trusted platform approval cards and quoted-start API/MCP flows. | Persist knowledge-draft quotes in durable jobs and recheck before retrieval/model work. Unknown estimates are refused where a quote is required. | A quoted estimate is **not** a guaranteed provider bill cap. Runtime accounting and budget enforcement remain separate. Legacy jobs without a quote retain their compatibility contract. [R5] |
| [#3442](https://github.com/vstorm-co/agenticos/pull/3442) | The run person receives the right approval link and wording. | Inbox/notification delivery and approval email, linking to the person's conversation. | Integrated with #3402 instead of copying its notification delta alone. Recheck pending status, trusted platform origin and current person; strip internal routing fields from mail data. | A stored notification cannot preserve authority after the call/person changes. Other approvers do not gain the person's authority. [R8] |
| [#3441](https://github.com/vstorm-co/agenticos/pull/3441) | Externally authored Improve/eval text is explicitly marked as untrusted tool-result data. | Model-facing tool results; no console layout change. | Kept read authorization at the service boundary and separated external prose from platform instructions/decision summaries. | An envelope establishes an instruction boundary; the external prose is still content the model reads. [R5] |
| [#3440](https://github.com/vstorm-co/agenticos/pull/3440) | Show dataset helper guidance and its author before an Improve start. Dataset settings distinguish editable guidance from read-only platform rules. | Improve start/estimate and dataset helper settings. | Guidance supplements rather than replaces platform instructions. Estimates and execution use the same composition. Authorship is server-owned and names only an active member of the same organization. | No email or cross-organization identity disclosure. Historical/unavailable authors may have no display attribution. [R7] |
| [#3427](https://github.com/vstorm-co/agenticos/pull/3427) | iPhone app-icon quick actions reach an already connected app scene. | Native iOS home-screen shortcuts. | Verified the actual QuickActions enum against the installed iOS Simulator SDK and preserved existing deep-link routing. | Cold-launch shortcut delivery remains unsupported by this patch. No simulator device/runtime was installed, so no complete app/device acceptance is claimed. [R6] |
| [#3426](https://github.com/vstorm-co/agenticos/pull/3426) | iOS can request microphone consent for dictation and voice calls instead of terminating for a missing purpose declaration. | Native microphone permission prompt. | Keep generated and shipped plist values consistent and add the four native locales already used by the app. | Plist/packaging checks passed; actual microphone consent and voice operation on an iPhone remain unverified locally. [R6] |
| [#3425](https://github.com/vstorm-co/agenticos/pull/3425) | Fresh sign-in returns to chat or another valid destination instead of looping back to sign-in. | Login/auth guard and return-target handling. | Extend classification to encoded and localized auth paths while retaining strict same-origin validation. Check compatibility with provider-only sign-in. | This does not broaden accepted redirect origins or reinterpret reserved URL separators. [R6] |
| [#3416](https://github.com/vstorm-co/agenticos/pull/3416) | External MCP clients receive destructive-action hints and confirmation guidance for always-confirm platform operations. | MCP tool metadata; no new console screen. | Kept hints aligned with existing hard in-product gates; did not treat a client annotation as server authorization. | MCP hints are advisory to clients. Required platform confirmations remain enforced by AgenticOS. [R5] |
| [#3402](https://github.com/vstorm-co/agenticos/pull/3402) | A Member/Builder can answer their own verified platform call without organization-wide approval authority. | Personal live cards, parked calls, approval queue and channel continuations. | Require bound platform provenance, the same run person and a fresh personal session. Other approvers may reject but cannot release work as that person. Ownerless continuation cannot borrow the approver's authority. | API keys, impersonation and publisher fallbacks cannot supply personal consent. Deployment changes still require deployment authority. Necessary person-only/ownerless guards were included; unrelated parent features were excluded. [R8] |
| [#3453](https://github.com/vstorm-co/agenticos/pull/3453) | Stored Improve/assistant failures can be translated using stable codes and numeric parameters. | Failed run/session/assistant detail views. | Keep technical detail separately; clear sentence, code and parameters together on retry. Preserve uncoded historical results. | Unknown codes or missing required counts fall back to the saved server sentence. Not every historical free-text error can be backfilled accurately. [R9] |
| [#3452](https://github.com/vstorm-co/agenticos/pull/3452) | Eval comparisons and merge refusals use localized reason text. | Eval/Improve comparison and merge-decision views. | Use closed reason types and count-only interpolation; align Turkish reasons with the outcomes this train actually emits. | User-authored names/errors are not interpreted as translation parameters. Legacy/unknown reasons keep their original sentence. [R9] |
| [#3451](https://github.com/vstorm-co/agenticos/pull/3451) | Complete French and Turkish Improve/eval/assistant copy for the selected screens. | French/Turkish console catalogs on those surfaces. | Merge by current keys/argument contracts rather than importing source-parent features; repair the Turkish exact-singular selector branch. | Catalog checks are not a linguistic review by native speakers. Other feature translations remain governed by the train's normal seven-locale checks. [R9] |
| [#3434](https://github.com/vstorm-co/agenticos/pull/3434) | Routine owners can follow the agent, ask every time where supported, or disable individual tools. The previously backend-only change now has a grouped/searchable UI. | Routine tools/access dialog. | Preserve restrictions for temporarily unavailable tools; show them for explicit removal. Prevent account/organization changes from leaking cached state. Explain clearing legacy standing consents before saving. | Rules can only narrow agent/platform policy. Required approvals cannot be released. New routines retain automatic eligible tools and one shared chat. Delegates keep their own rules. [R10] |
| [#3403](https://github.com/vstorm-co/agenticos/pull/3403) | Improve session reads/lists require `runs:view` after agent access resolution. A caller who may stop work but cannot read it receives only a minimal stop receipt. | Improve page, lists, HTTP/MCP reads and stop action. | Do not hydrate timeline, attempts, financial/dataset details or measurement noise during an unauthorized stop; clear cached details in the console. | Agent visibility alone does not grant run/session visibility. Stop permission does not become read permission. [R8] |
| [#3105](https://github.com/vstorm-co/agenticos/pull/3105) | Create authenticated reusable Event sources, inspect a live sample and attach independent routine/workflow subscribers. Existing dedicated webhook URLs keep working. | Event sources page, credential/source dialogs, dashboard widget and routine/workflow trigger pickers. | Preserve raw-byte signature verification, receipt-time consent, tenant-bound Vault credentials and commit-before-dispatch/capture. Include the page in role presentation controls. Imported workflow source IDs are omitted and explicitly require reconnection. | Shared sources acknowledge asynchronously; synchronous Respond to webhook needs a dedicated endpoint. Sample access does not grant target access. #3274 prompt interpolation was not selected. Live external provider deliveries are not claimed. [R11] |
| [#3305](https://github.com/vstorm-co/agenticos/pull/3305) | Deterministic Python workflow code can call named/versioned native actions; each call has a durable child step with normal authorization, approval, budget and result handling. | Python action binding editor, snippets/guidance, live workflow canvas and run detail. | Resource bundles walk each bound action's owned config schema. Remap table IDs/versions together; refuse source column subsets. Reject forged action scopes on other node types. Reuse proven receipts and never blindly repeat an uncertain external write. | Monty is pinned to 1.6.0 for checkpoint compatibility. At most 100 calls, bounded checkpoints/output and no recursive Python-action nodes or direct graph wiring. Trigger/output response nodes cannot be called. No arbitrary host Python or hidden model call is introduced. [R12] |
| [#3456](https://github.com/vstorm-co/agenticos/pull/3456) | Dutch native desktop setup and language handoff to the console. | Native start/setup screen, language picker and local runtime progress. | Complete the ten runtime transition messages in every supported native locale; verify translation parity and language handoff. | Native startup supports en/pl/de/tr/nl/pt; French remains a console locale. Browser rendering of the native HTML is visual evidence, not a packaged Tauri run. |

## Requested issues implemented in the same train

| Issue | Resulting behavior | Visible surfaces | Review protections | Limits |
| --- | --- | --- | --- | --- |
| [#3300](https://github.com/vstorm-co/agenticos/issues/3300) | Deployment availability bounds organization role defaults and personal console choices. Configure navigation, optional product prompts, approved MCP/Skill discovery and dashboard defaults. | Organization role presentation, personal preferences, sidebar/command navigation, catalogs, dashboard and role preview. | Null inherits; empty selections remain intentional. Filter catalogs before counts/pagination. Preserve existing authorized bindings and private Skill-copy isolation. Explicit Save/Discard and owner-scoped drafts. | Presentation never grants/revokes resource authorization. Role preview is permission-bounded navigation, not impersonation. Personal layouts override role defaults; security/service notices remain visible. [R4] |
| [#3302](https://github.com/vstorm-co/agenticos/issues/3302) | Organization audiences control who sees chat costs; members can hide permitted costs further. | Organization/personal cost settings; history, shared chat, live/replayed completion, delegation and Q&A. | Redact on the server for the actual reader, recheck socket membership and preserve original accounting/live frames. Failed policy reads withhold financial metadata without losing a saved answer. | Hiding costs does not stop spend/accounting/budget enforcement, grant spend permissions, or remove arbitrary financial text authored by the agent/tools. Null preserves the existing visible default. [R4] |
| [#3303](https://github.com/vstorm-co/agenticos/issues/3303) | Show configured sign-in providers and optionally disable local password admission at deployment level. | Deployment settings, login, register and recovery/email-link pages. | Enforce policy server-side, including old reset/email tokens; refuse disabling without a configured provider. Separate saved policy from the operator recovery override. | Existing sessions/directory authentication keep their contracts. Recovery override neither creates accounts nor grants roles. Preview SSO is a dummy local provider, not live IdP acceptance evidence. [R4] |
| [#3382](https://github.com/vstorm-co/agenticos/issues/3382) | A saved chat answer replaces its interrupted live fragment after reconnection; still-running answers are followed again. | Chat recovery and interruption notice. | Covered by #3383 with the saved-segment/detached-run regression, rather than a second overlapping implementation. | No fabricated completion while the run is still missing/unavailable. [R4] |

## Final interaction and mechanism review

Project chat counts use a badge on the Chats tab without a second list toolbar or
an additional query. Navigation editing keeps Save/Discard pinned outside the
scrolling choices. Organization actions use responsive grids on phones; Architect
no longer squeezes its description beside the Builder action. Speech-to-text
writes lock their own fields while pending, retain stored catalog selections
when discovery fails and expose Retry without changing saved configuration.

The workspace audit found and repaired one binary continuation defect: a
successful Project-to-agent inspection now records the observed Project digest,
so a later revised binary can be published. A competing Project change still
requires another inspection. Validation regexes cover identifiers, paths and
hashes, not inferred user intent. Transfers remain explicit copies; their digest
checks do not claim an atomic compare-and-swap against arbitrary shell writers.

## Acceptance evidence and limits

The maintainer's subsequent acceptance feedback separates Project files from the
agent's own execution environment according to discussion #3272. Agent execution
is now the default in attached Project chats. Explicit binary file transfers,
executor-aligned generic tools, compact chat controls, resource/export identities,
Python Actions guidance, compact sidebar customization and non-flickering settings are
described in [the follow-up contract](project-workspaces-3272.md). Earlier screen
captures below document the previous candidate; fresh captures and exact-head CI
are required for this follow-up. The subsequent feedback removes the resource
picker expansion control, aligns the knowledge count with its tabs, keeps only
the top Project chat action, rounds the conversation search focus and places
sidebar customization beside notifications.

The definitive full-CI evidence is the latest source SHA's checks on PR #3455.
A passing source PR, focused local test or combined report does not replace that
check. Earlier aggregate runs exposed stale asynchronous fixtures, incomplete
Projects UI inventories, an eager ingest-to-routine import, unstable xdist IDs,
ambiguous browser selectors and missing branch coverage. Their repairs retain
authorization refusals, completion assertions and the existing coverage gates.

Actual browser exercises completed on the production frontend artifact built
by CI for source `176a81e9d`, with synthetic local data:

- A private agent export/reimport preserves exact Context whitespace and reuses
  the explicitly selected Context ID. The copied agent has its own identity.
- Workflow dependency import/export completes without publishing the draft.
- A real durable worker imports and exports a knowledge ZIP containing two
  documents and three assets. Exported asset sizes and SHA-256 digests match.
- Python action bindings and routine per-tool controls have desktop/mobile
  previews. Their demonstration workflow is unpublished and the routine paused.
- Project controls distinguish files-only storage from an executable service.
  The authorized file picker exposes Agent and Project origins separately. The
  Project file is read successfully. The unused Agent origin may be unavailable;
  the UI reports that state instead of silently reading the same path elsewhere.
- The profile editing journeys pass on desktop and phone. Catalog readability,
  body completion and geometry pass in both themes at 390 px. Dataset helper
  guidance uses its current label in the real browser journey.

One authorized real `anthropic/claude-haiku-5.5` smoke run selected Project file
context and read `release-plan.md`. Its persisted answer correctly requests
reviewing desktop/mobile views. Its recorded cost is USD 0.001349. This is an
integration check, not a provider benchmark. Both the preview organization and
the review agent have a USD 5 monthly cap. Provider credentials are in the
application Vault; local master-key material stays outside the repository.

Approval-card and Improve comparison previews use actual components with
explicitly synthetic payloads. They do not prove live external publication or
provider billing. The native iOS changes have source/CI evidence, with no
physical-device acceptance. No production data, deployment or release changed.

The local queue worker services manually admitted jobs. Recurring deployment
sweeps are deliberately absent from this acceptance instance. This prevents a
left-open preview from starting background model work; it does not represent a
production scheduler test.

## Operator review before a later release

1. Drain API admission and old workers for the coordinated schema/worker upgrade; this train is not claiming rolling compatibility for the new non-null Improve snapshot field and new durable job kinds.
2. Apply the joined migration head `0372_release_train.py`, preserving every source revision identity. Relevant branches include attempt receipts, Event sources, routine restrictions, holdout snapshots, coded failures, KB snapshots and workspace-origin references.
3. Preserve the exact Monty 1.6.0 pin while durable checkpoints exist. Treat a later interpreter upgrade as checkpoint-compatibility work.
4. Knowledge snapshots carry no searchable vector index. Destination credentials/endpoints and explicit indexing remain operator/member actions. Snapshot downgrade is protected against orphaning stored content.
5. Review actual desktop/mobile captures, complete exact-head CI and obtain maintainer acceptance before merge. A version cut and deployment need the later explicit authorization.

## Review reports

Paths below are repository-only engineering evidence, not claims that every UI or live provider has been exercised.

- **R1 — Portable resource contracts:** `docs/design/project-runtime-and-portability.md`. Its early architecture/status paragraphs are historical; use the later implementation-specific reports and current code for completed behavior.
- **R2 — Knowledge snapshots:** `docs/design/portable-knowledge-snapshots.md`.
- **R3 — Project execution and origins:** `docs/design/project-run-context-review-2026-11-26.md`; `docs/design/chat-file-origins.md`.
- **R4 — Console policies, safe areas, recovery and API steering:** `docs/design/release-train-2026-11-25.md`. Its per-stage “pending” statements record that stage; final aggregate acceptance remains separate.
- **R5 — Quotes, approval descriptions, MCP hints and untrusted text:** `docs/design/platform-approval-review-2026-11-25.md`.
- **R6 — Sign-in, composer and native iOS fixes:** `docs/design/release-mobile-chat-review-2026-11-25.md`.
- **R7 — Improve guidance, diffs and holdouts:** `docs/design/review-improve-evidence-2026-11-25.md`.
- **R8 — Own-person approvals, notifications and Improve reads:** `docs/design/own-platform-approval-review-2026-11-26.md`.
- **R9 — Translated catalogs and failure/reason codes:** `docs/design/review-localized-failures-2026-11-26.md`.
- **R10 — Routine tool controls:** `docs/design/routine-tool-settings-review-2026-11-26.md`.
- **R11 — Reusable sources:** `docs/design/review-event-sources-2026-11-26.md`.
- **R12 — Python actions:** `docs/design/workflow-python-actions-review-2026-11-26.md`.
- Source selection and intentionally unselected candidates: `docs/design/release-candidates-2026-11-25.md`.
