# Media generation nodes for workflows

**Status: proposal only.** This document adds no workflow node, generation
request, provider credential, migration or running background job.

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
The registry presently includes `image.transform`, not the proposed generation
node ids below.

## Proposed node contracts

| Id and version | Config | Input | Output | Effect and retry |
|---|---|---|---|---|
| `image.generate@1` | Catalog provider/model, authorized secret id, size/quality defaults, output filename and bounded timeout | Prompt plus optional supported source-image `FileRef` | Image `FileRef`, actual MIME/dimensions, generation receipt | `write`, spends budget, `retry_guarantee=none` initially |
| `video.generate@1` | Catalog provider/model, secret id, aspect/resolution/duration/sound defaults and bounded timeout | Prompt plus optional supported starting-image `FileRef` | Video `FileRef`, actual MIME/duration where known, generation receipt | `write`, spends budget, `retry_guarantee=none` initially |
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

Proposed result envelope, using the existing `FileRef` schema for the file field:

```json
{
  "file": {
    "kind": "file",
    "file_id": "00000000-0000-4000-8000-000000000001",
    "content_type": "image/png",
    "byte_size": 129034
  },
  "media_type": "image/png",
  "width": 1024,
  "height": 1024,
  "receipt": {
    "operation_id": "<server operation id>",
    "provider": "example_provider",
    "model": "example_model",
    "submitted_at": "2026-11-14T15:00:00Z",
    "cost_source": "catalog_estimate",
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

Extract a narrow generation service used by both the existing agent tool and
the workflow node. Its explicit inputs are the resolved provider request,
authorized credential adapter, input bytes/metadata, timeout, cancellation and
operation receipt sink. It does not choose an organization, read an ambient
admin account or decide authorization.

Keep budget and storage ownership with the caller. The agent tool continues its
current admission and generated-media flow; the workflow adapter uses workflow
budget reservations and scoped workflow files. The shared provider call must not
book the same charge a second time.

The current video helper waits for bytes and may poll provider jobs internally.
That is not evidence of crash-safe workflow resumability. Refactor submit,
observe and collect only as far as each provider's supported contract permits,
while preserving existing agent-tool behavior and its regression tests.

## Durable operation and retry boundary

Add a proposed media-operation record linked to organization, workflow run,
node attempt, request hash, provider/model, secret reference/generation, phase
and provider receipt where available. Retain no credential values.
No migration number is reserved by this design.

| Phase | Recovery behavior |
|---|---|
| `prepared` | Budget reserved, validated inputs and authority recorded; no provider submission claimed. |
| `submitting` | Durable admission precedes the outbound request. A crash here is uncertain unless provider idempotency proves otherwise. |
| `submitted` | Provider job/operation id is known; poll that exact job, never submit another. |
| `collecting` | Retrieve output with bounded size/type checks and restricted provider destinations. |
| `stored` | A workflow file reference is committed and can be returned without generation. |
| `unknown` | No automatic retry; surface uncertainty and retain the estimated spend pending reconciliation. |
| `failed`, `cancelled` | Preserve receipt and spend semantics; do not assume the provider cancelled or refunded. |

Use an idempotency key only where the provider documents and honors it. A stable
T3OS operation id alone cannot make a remote generation idempotent. Initial
node registration declares `retry_guarantee=none`; the generic workflow retry
button must not resubmit a potentially accepted generation automatically.

A known job may be polled after restart only with its original credential,
authority and receipt. An ambiguous submission stays unknown. An explicit new
generation creates a new operation and requires a new budget reservation.
Recording the previous failure remains part of the run history.

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

Resolve source files through `workflows.files.load` or its streaming boundary.
Reject a forged `FileRef`, cross-run/cross-tenant reference, expired source,
oversized decompression, mismatched media bytes and unsupported input type.
Reuse current limits; do not trust extensions or remote Content-Type alone.

Provider output retrieval accepts only the destinations and redirects supported
by the reviewed adapter. Do not expose arbitrary download URLs to the server.
Bound bytes, dimensions and duration before storage and preview.

Reserve estimated maximum spend before submission using the workflow budget
service, including concurrent node reservations. Refused-before-submission work
releases its reservation. Accepted, timed-out or unknown work retains an
appropriate estimate until actual usage or a supported reconciliation arrives.
The receipt states whether spend is reported or estimated.

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

Disabling new generation blocks new admissions but keeps stored outputs and
receipts readable under existing permissions. Known jobs may be reconciled under
a bounded operator policy; disabled mode never starts replacements. Retention
and cleanup continue.

Do not remove a registered node version while a published graph references it.
Rollback keeps a readable compatibility definition and a clear disabled-state
error until those graphs are migrated. Existing agent image/video tools and
`image.transform` are not disabled by this feature's rollback.
