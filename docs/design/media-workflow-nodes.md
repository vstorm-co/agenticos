# Media generation nodes for workflows

**Status: locally implemented, unavailable by default.** Asset inspection,
strict shared provider execution, durable image/video workflow operations and
the companion canvas controls have focused synthetic validation. The runtime
checkpoint remains subject to its final scoped regression/coverage gates,
combined release validation and separately authorized deployment acceptance.

Baseline: T3OS `080c12941ed06cce2e92b6b03910e94ace36469e`, inspected on
14 November 2026. Benchmark:
[OpenBot v0.71.0](https://github.com/nightly-labs/openbot/releases/tag/v0.71.0)
and its [Image, Video and Asset canvas release notes](https://openbot.run/changelog).
This is an independent design using T3OS's existing generation services.

## Outcome and existing capability

Add dedicated **Generate image**, **Generate video** and **Asset** steps to the
workflow canvas. Connect an input asset to image/video generation and pass a
typed file output to previews, file transforms and later workflow steps.

T3OS already generates images and videos through agent tools. Workflows can call
an agent, MCP server or HTTP API, and already manipulate files and transform
images. The missing layer is a direct, typed media node with explicit model,
credential, budget and retry behavior.

| Verified existing source | Integration decision |
|---|---|
| `backend/app/workflows/_registry.py` and `workflows/contracts/definition.py` | Register permanent ids and versioned config/input/output schemas; declare side effects, resource checks and retry guarantee. |
| `backend/app/workflows/nodes/agent_run/__init__.py` | Follow the budget-spending, resource-checked action-node pattern. |
| `backend/app/workflows/nodes/image_transform/__init__.py` | Preserve the existing image transformation node; generation is a different action. |
| `backend/app/agents/capabilities/image_generation/_toolset.py` | Extract reusable image-provider execution from the agent tool without duplicating metering. |
| `backend/app/services/video_generation/generation.py` and `clients.py` | Reuse video validation and provider clients; explicitly expose submission/receipt states before durable recovery is claimed. |
| `backend/app/services/image_models.py`, `video_models.py` | Use current catalog choices and constraints; no second hard-coded model list in the canvas. |
| `backend/app/workflows/files.py` and `workflows/contracts/io.py` | Output and load scoped `FileRef` objects with quotas; do not treat an arbitrary filename or URL as authority. |
| `backend/app/services/workflow_execution/budget.py` | Reserve and settle generation cost within the workflow budget, including parallel-node reservations. |
| `backend/app/services/generated_media.py` | Reuse storage/retention primitives only where scope permits; its organization-wide read policy must not widen workflow-file access. |
| `frontend/src/components/workflows/runs/run-files.tsx` | Show media outputs using the existing authorized run-file surface. |

See [workflow nodes](../reference/workflow-nodes.md) for the current node contract.
The registry preserves `image.transform` and registers the default-disabled
`asset.input`, `image.generate` and `video.generate` definitions. The published
[workflow guide](../workflows.md#media-inputs-and-generation) covers their
configuration, reservation display and recovery choices in all four site languages.

## Node contracts

| Id and version | Config | Input | Output | Effect and retry |
|---|---|---|---|---|
| `image.generate@1` | Catalog provider/model, authorized secret id, size/quality defaults, output filename and bounded timeout | Prompt plus optional supported source-image `FileRef` | Image `FileRef`, actual MIME/dimensions, generation receipt | `write`, spends budget, `retry_guarantee=none` |
| `video.generate@1` | Catalog provider/model, secret id, aspect/resolution/duration/sound defaults and bounded timeout | Prompt plus optional supported starting-image `FileRef` | Video `FileRef`, actual MIME/duration, generation receipt | `write`, spends budget, `retry_guarantee=none` |
| `asset.input@1` | Accepted media kinds, byte/pixel/duration limits, optional required input name | An authorized run input `FileRef` | The same validated `FileRef` and metadata | `read`, no generation spend, idempotent |

The initial Asset node accepts files supplied as authorized workflow inputs or
earlier node outputs. It is not an unrestricted URL fetcher or a new public media
library. Use the existing download node for separately authorized network fetches.
A future saved-asset picker must pin an accessible immutable asset version and
copy it into the run through the existing file-import boundary.

A catalog field unsupported by a chosen model is rejected at validation and
again before spending. The UI must not show an option that the provider will
silently ignore. Image editing is offered only where the provider adapter has a
tested input-image contract; it is not inferred from text-to-image support.

Result envelope, using the existing `FileRef` schema for the file field:

```json
{
  "file": {
    "kind": "file",
    "file_id": "00000000-0000-4000-8000-000000000001",
    "content_type": "image/png",
    "byte_size": 129034
  },
  "kind": "image",
  "media_type": "image/png",
  "byte_size": 129034,
  "width": 1024,
  "height": 1024,
  "receipt": {
    "operation_id": "00000000-0000-4000-8000-000000000002",
    "provider": "example_provider",
    "model": "example_model",
    "submitted_at": "2026-11-14T15:00:00Z",
    "cost_source": "catalog_estimate",
    "cost_usd": "0.034033",
    "held_usd": "0.640000",
    "outcome": "stored"
  }
}
```

The file id and metadata above are synthetic examples using the existing
Pydantic `FileRef` shape. The server verifies metadata against the stored file.
Do not put base64 media, credentials, temporary signed URLs or raw provider
responses in node outputs or the receipt.

## Canvas and run experience

The palette lists the three nodes with useful names and consistent file ports.
Selecting a provider narrows model and output options from the backend catalog.
A credential picker shows only eligible kinds and purposes; creating a key uses
the existing inline Vault flow.

An estimate appears before a test run, with the catalog price timestamp and its
assumptions. It is labelled an estimate. During execution the node shows
**Submitting**, **Generating**, **Saving**, **Complete**, **Failed** or
**Outcome unknown**, as backed by the durable operation record.

The run viewer previews an authorized output and allows download through the
normal file route. Downstream nodes use the typed file reference. A rerun warns
when it submits a new billable operation; it cannot look like a free preview
refresh.

The Asset inspector shows actual detected type and size, not only the uploaded
filename. Prompt and reference media remain subject to normal workflow visibility
and retention. A private asset cannot become visible to every organization member
because generated media has a broader store.

## Shared generation boundary

### Implemented provider boundary

The shared boundary for the image agent tool and workflow integration is
`backend/app/services/image_generation.py`. The existing agent tool retains its
admission, metering and storage ownership. Strict workflow execution owns and
closes its provider clients, fixes the catalog endpoints, disables transport and
model-correction retries, rejects paid-request redirects and admits one model
request. OpenAI Responses also receives `max_tool_calls=1` in the actual request
body; the installed SDK has no named setting for that field. The workflow caller
supplies its catalog-validated token cap, request options and input-image bytes.

Strict OpenAI image requests also pin `service_tier="default"` in the final HTTP
body. The [Responses create reference](https://developers.openai.com/api/reference/resources/responses/methods/create)
defines this as standard pricing; an omitted tier inherits the project's setting.
The [Fast mode guide](https://developers.openai.com/api/docs/guides/fast-mode)
allows a premium project default, so omission does not establish the catalog's
standard-price bound. Actual SDK/HTTP tests prove the strict request overrides a
caller tier and ordinary agent requests retain their existing tier behavior.
If the response reports a different tier, the operation preserves its entire
monetary hold, records only a closed mismatch flag, and leaves accounting
incomplete without booking a standard-price estimate as that fee. This hold is
unresolved accounting, not proof of an upper bound on an unexpected premium bill.
The current Google request default is standard according to its
[service-tier guide](https://ai.google.dev/gemini-api/docs/generate-content/priority-inference).

The video facade accepts a frozen `VideoReceipt` containing only provider, API,
model, kind and an opaque job/file id. New receipts are durably acknowledged by
the caller before polling or collection. A matching receipt resumes that exact
job without another submission. A failed journal propagates; a lost submission
without a receipt remains uncertain. Google inline responses have no resumable
file receipt. Protected workflow collection validates and pins every download
hop to public addresses, bounds the body, and permanently drops authentication
headers after the first cross-origin redirect. Provider cancellation and billing
limitations still apply. These provider primitives alone do not establish
workflow crash recovery, current authority, budget holds or atomic file storage.

Focused tests use the actual image SDKs against synthetic HTTP transports and
the video facade against synthetic provider/pinned-download transports. The
workflow tests additionally use real PostgreSQL claims and isolated local file
storage. They make no paid requests. Combined release and live acceptance remain pending.

### Workflow integration contract

The shared generation service is used by the existing agent tool and workflow
node. Its explicit inputs are the resolved provider request,
authorized credential adapter, input bytes/metadata, timeout, cancellation and
operation receipt sink. It does not choose an organization, read an ambient
admin account or decide authorization.

Keep budget and storage ownership with the caller. The agent tool continues its
current admission and generated-media flow; the workflow adapter uses workflow
budget reservations and scoped workflow files. The shared provider call must not
book the same charge a second time.

The video helper still owns supported provider polling, while its awaited
receipt callback commits the workflow journal before any collection. A resumed
call supplies that same closed receipt; it cannot fall back to submission.
Providers without a usable receipt retain an unknown outcome after a lost
acknowledgment. Existing agent-tool behavior remains independently tested.

### Workflow catalog and reservation bounds

The nullable `workflow` member of each image/video catalog model is the workflow
admission contract. A null member does not admit generation. Legacy agent options
remain readable independently. The editor renders the same catalog defaults,
supported options and reference-image capability that the runtime validates.
The request accepts an organization-scoped `api_key` whose purpose exactly equals
the selected provider; a personal connection or `custom` purpose does not qualify.

Image holds use dated catalog inputs verified on 16 November 2026. A hold is a
conservative reservation ceiling, not a predicted bill or an incurred charge.
Google's input bound is the selected model's whole published context limit;
the output bound is the lower request limit supplied to the strict shared SDK
executor. The output rate is the most expensive permitted output modality,
covering text, thinking and image tokens together. Authorized reference bytes
still require bounded decoding and inspection before dispatch.

| Google model | Input-token ceiling | Request output-token cap | Input/output USD per million | Reservation USD |
|---|---:|---:|---:|---:|
| Gemini 3 Pro Image | 65,536 | 8,192 | 2 / 120 | 1.114112 |
| Gemini 3.1 Flash Image | 131,072 | 8,192 | 0.50 / 60 | 0.557056 |
| Gemini 3.1 Flash Lite Image | 65,536 | 4,096 | 0.25 / 30 | 0.139264 |
| Gemini 2.5 Flash Image | 65,536 | 8,192 | 0.30 / 30 | 0.265421 |

The derivation is `(input ceiling × input rate + output cap × output rate) / 1e6`,
rounded upward to six decimal places. Lite accepts only its documented 1K output.
The 2.5 adapter receives no unsupported size setting. Aspect choices are limited
to those represented by the installed SDK. Sources: the individual model pages
linked by the catalog, [Google pricing](https://ai.google.dev/gemini-api/docs/pricing),
[image generation](https://ai.google.dev/gemini-api/docs/image-generation) and
[thinking/output limits](https://ai.google.dev/gemini-api/docs/thinking).

OpenAI workflow generation is initially text-only. It requires an explicit
catalog size/quality, one image tool call, and an 8,192-token caller output cap.
The reservation includes the GPT-5.4 caller's whole 1,050,000-token context at its
long-context input rate, its capped output at the long-context output rate, and
the separate image tool's input and output. A tool prompt is limited to 32,000
Unicode characters; four UTF-8 bytes per character conservatively bounds its
byte-level input tokens. GPT Image 1.5 and 1 Mini have the documented pre-2
size/quality output-token table; tests verify every advertised ceiling covers
those counts at their respective $32 and $8 per million image-output-token
rates, as well as their model-specific displayed price plus one rounding unit.
For example, a medium 1024×1024 GPT Image 1.5 request reserves $6.109320, which
deliberately exceeds the expected cost of a short prompt.

GPT Image 2 has `workflow: null`. Its current guide calls its output costs
estimates and explicitly excludes it from the fixed output-token table.
Adding a rounding unit to an estimate does not establish a hard upper bound.
The legacy agent binding remains available; workflow admission requires a
documented output bound before this model can be enabled. Sources:
[GPT Image 1.5 pricing](https://developers.openai.com/api/docs/models/gpt-image-1.5),
[GPT Image 1 Mini pricing](https://developers.openai.com/api/docs/models/gpt-image-1-mini),
[GPT Image 2](https://developers.openai.com/api/docs/models/gpt-image-2),
[GPT-5.4 limits](https://developers.openai.com/api/docs/models/gpt-5.4),
[API pricing](https://developers.openai.com/api/docs/pricing),
[image generation](https://developers.openai.com/api/docs/guides/image-generation)
and [the image API prompt limit](https://developers.openai.com/api/reference/resources/images/methods/generate).

Returned usage and the selected image output may support a `catalog_estimate`
of incurred fees. A returned `revised_prompt` does not establish that it includes
all billed image-tool input. That tool-input component therefore remains held
until provider evidence reconciles it, including after a verified image is
stored. Neither a reservation nor an unproven maximum is booked as incurred
spend, and an estimate is never mislabeled as an exact bill or a partial lower
bound. The durable record retains its original dated price basis, without
storing prompt text or raw provider responses.

Video workflow metadata reuses the current dated per-second catalog rates, with
all advertised resolutions priced before admission. The same helper supplies
the editor and request defaults: first catalog resolution/aspect, five seconds
clamped to the model's range where duration is selectable, and sound disabled
for optional-audio models. Fixed-audio models receive no audio toggle; models
that choose their own duration reserve the catalog maximum. Optional sound-on
requests remain covered by the catalog's required sound-on rate.

## Durable operation and retry boundary

`0343_workflow_media_operations`, after `0342_browser_credential_plans`, adds
the operation record and tenant lineage constraints. It links the organization,
run, node, original and collecting attempts, immutable request hash, provider/API/
model, secret reference and authorization generation, original price basis,
phase, closed provider receipt, and preassigned output identity. It stores no
credential value, prompt, raw provider payload or download URL. Downgrade refuses
while operation evidence remains.

| Phase | Recovery behavior |
|---|---|
| `prepared` | Budget reserved, validated inputs and authority recorded; no provider submission claimed. |
| `submitting` | Durable admission precedes the outbound request. A crash here is uncertain unless provider idempotency proves otherwise. |
| `submitted` | Provider job/operation id is known; poll that exact job, never submit another. |
| `collecting` | Retrieve output with bounded size/type checks and restricted provider destinations. |
| `stored` | A workflow file reference is committed and can be returned without generation. |
| `unknown` | No automatic retry; surface uncertainty and retain the unresolved hold pending reconciliation. |
| `failed`, `cancelled` | Preserve receipt and spend semantics; do not assume the provider cancelled or refunded. |

The existing outbox claim token fences admission, collection and output commit.
Media requires an exact token even though nonmedia dispatch contexts retain
their compatible optional default. One transaction wins `prepared → submitting`
before the external effect. Reclaiming `submitting` cannot send another POST.
A stable T3OS operation id is not remote provider idempotency; node registration
therefore retains `retry_guarantee=none`.

A known job may be polled after restart only with current authority, the original
credential generation and exact receipt. The canonical dispatcher alone grants
that collection attempt; it keeps its ordinary retry ceiling and backoff. Known
collection may bypass fresh spend admission, but receives no new submission
reservation. A preassigned, verified output can instead recover the same file.
Unknown work refuses in-place `run_again` with `MEDIA_RECONCILIATION_REQUIRED`.
An explicitly authorized replacement after a definite failure, or generation
executed in a separate retry run, creates new billable work. Earlier holds remain.

Cancellation stops local polling and invokes provider cancellation only where
supported. A provider may finish and bill after a local timeout; report that
uncertainty. Permission revocation prevents downloading or exporting output even
if the remote provider already accepted the job.

## Authorization, storage and spend

A node's `resource_check` verifies its model/credential/input resources during
graph validation. The handler rechecks the run's own principal at execution and
before output is committed. A workflow publisher's access cannot silently lend
a personal subscription to schedules, API-key jobs or another member.

Start with organization-approved API credentials that the current generation
adapters already support. Personal subscription-backed media requires a distinct
provider entitlement and authority contract; the presence of a chat subscription
is not enough.

Resolve source files through `workflows.files.load_verified` and its bounded stream.
Reject a forged `FileRef`, cross-run/cross-tenant reference, expired source,
oversized decompression, mismatched media bytes and unsupported input type.
Reuse current limits; do not trust extensions or remote Content-Type alone.

Provider output retrieval accepts only the destinations and redirects supported
by the reviewed adapter. Do not expose arbitrary download URLs to the server.
Bound bytes, dimensions and duration before storage and preview.

Reserve a conservative maximum before submission under the existing organization
file/budget admission lock. Durable holds survive attempt lease expiry and key
deletion. Budget checks avoid counting a matching in-flight attempt reservation
twice, then retain the durable commitment when that attempt ends. A proved
unsubmitted interruption releases its hold. An unused maximum is never incurred
spend. The operation records `cost_source=reported|catalog_estimate` and
`accounting_complete`; an estimated fee is not labeled a partial lower bound.

New incurred facts are booked once against the original canonical NodeAttempt,
run/ancestor totals and node-spend ledger. A later fee sweep books late evidence
without dispatching work. Organization budget checks, including the ordinary
agent callback, add held and unbooked amounts; reporting continues to read booked
fees. Retention and workflow deletion refuse unresolved USD, byte holds or
unbooked fees, including superseded operations.

Output identity is committed before the provider effect. After inspection, the
journal records its digest and metadata before an atomic local blob write.
`files.persist_reserved` validates the exact organization/run/node/attempt/token,
digest and quota; it does not commit. The caller rechecks authority and key
generation, then commits the file row and stored-operation link together.
Concurrent collectors return the same identity. Cancellation between blob write
and database commit leaves recoverable bytes and the original journal.

`POST /api/v1/workflows/media-estimate` uses the same reservation helpers and
authorized key metadata, without key unwrap or a provider request. Its closed
assumption codes support translated display. Existing authorized node-run pages
add `media_operation`: phase, opaque operation id, held/incurred/booked cost,
cost source, accounting completeness, aggregate unresolved cost, receipt
availability and retry effect. They expose no extra secret or run authority.

## Implementation slices and acceptance

| Slice | Deliverable | Required evidence |
|---|---|---|
| 1. Shared execution boundary | Provider service extraction preserving agent tools | Existing image/video tests remain green; one call and one charge per operation; secrets absent from errors/traces. |
| 2. Asset node | Typed scoped media input and metadata | Forged/cross-tenant/cross-run references refused; actual bytes validated; existing file retention and quotas honored. |
| 3. Image node | Catalog-driven image generation and authorized output | Budget refusal before provider call, concurrent reservations, output MIME checks, denied credential, timeout/unknown outcome fixtures. |
| 4. Video node | Supported job receipt and bounded collection | Crash after acceptance polls the same job; absent receipt remains unknown; cancellation does not claim a provider refund. |
| 5. Canvas and run UI | Forms, ports, estimates and media preview | Keyboard operation, incompatible settings, stale model catalog, unreadable file and explicit billable rerun behavior. |

Use fake provider adapters to test state transitions, not paid calls in CI.
A small separately authorized live acceptance per enabled provider must verify
its request, output, price assumptions, cancellation and error contract before
the adapter is described as supported for workflow generation.

Add registry/layout tests, schema round-trip tests, resource-check tests and
focused workflow/budget/file tests. Update generated node references, onboarding,
palette translations and run-file previews in implementation PRs.

## Rollout and rollback

Register the nodes behind a disabled deployment flag and expose them first to
synthetic test workflows. Enable Asset, then Image, then supported Video
providers. Old published graphs retain their exact node versions.

`WORKFLOW_ASSET_INPUT_ENABLED`, `WORKFLOW_IMAGE_GENERATION_ENABLED` and
`WORKFLOW_VIDEO_GENERATION_ENABLED` are separate default-false flags. Disabling
generation refuses handler execution, including provider collection, while
stored files and safe journal summaries remain readable under existing
permissions. The fee-only sweep can book evidence already received. Retention
continues for ordinary runs but preserves unresolved media commitments. A known
job needs its node enabled and current authority before canonical collection;
there is no second operator dispatcher or implicit replacement path.

Do not remove a registered node version while a published graph references it.
Rollback keeps a readable compatibility definition and a clear disabled-state
error until those graphs are migrated. Existing agent image/video tools and
`image.transform` are not disabled by this feature's rollback.
