# #1791 — Workflows: isolated Python, HTTP files and image processing

Design for [issue #1791](https://github.com/vstorm-co/agenticos/issues/1791),
child of [#56](https://github.com/vstorm-co/agenticos/issues/56). Depends on
[#1786](1786-node-contracts.md) (`NodeDefinition`, `FileRef`, graph
validation), [#1788](1788-durable-execution.md) (the dispatcher, the
reconciler, `Waiting`/`Uncertain`) and [#1790](1790-error-foreach.md)
(`NodePolicy`, `WorkflowError.bypassable`, the foreach scope model), all
treated as fixed. Every node below is a `NodeDefinition` registered the way
`debug.echo` is, returns the `Completed`/`Waiting`/`Failed`/`Uncertain` union
#1788's dispatcher already advances, and runs inside a `control.foreach` body
like any other action node — nothing here touches `scope_path`, #1790 already
threads it through `NodeRun`/`NodeAttempt`.

## Reused vs. new

Reused untouched: `PinnedAsyncClient`/`resolve_pinned_url`
(`app/core/pinned_http.py`) for every outbound URL; `get_file_storage()`
(`app/services/file_storage.py`); `app.core.vault` for `http.upload`'s auth,
as #1789's `http.request` already uses it; the RAG ingestion pipeline's
text-layer/OCR-need preflight (`app/services/rag/documents.py`) to *detect* a
scanned PDF, not to OCR it; `pillow`/`python-docx`/`pymupdf`, already backend
dependencies; `CHAT_IMAGE_MAX_PIXELS`'s check-before-decode pattern
(`app/core/config.py`); `sandboxd` and its runtime catalogue
(`docs/sandbox.md`); `AttachmentRouter`'s `BinaryContent` construction
(#1789's `agent.run`). New: a storage-backed table `FileRef` resolves
against; ten node packages; one sandbox runtime entry; sandbox-job
reconnect logic.

## Module layout

```
app/workflows/nodes/
  http_download/  http_upload/  file_read/  file_write/  text_extract/
  convert_csv_json/  convert_json_csv/  convert_text_to_file/  convert_pdf_to_png/
  image_transform/  python_simple/  python_sandbox/
app/services/workflow_execution/
  sandbox_jobs.py     # deterministic session key, stage/execute, reconnect not restart
app/db/models/workflow_file.py       # WorkflowFile — the real backing FileRef resolves to
app/repositories/workflow_file.py
app/core/catalog/sandbox_runtimes.json   # + "workflow-python": no network, no LibreOffice
```

Each node package is `{__init__, _handler, README}`, mirroring `debug_echo/`.

## `FileRef` becomes storage-backed, without changing its shape

Shared-contracts commits #1791 to not changing `FileRef`'s three fields
(`file_id`, `content_type`, `byte_size`) — "only adding what enforces it."
So the field(s) this issue adds land on a **new sibling table**, not on
`FileRef`: an unbacked reference should carry an id and a declared type; the
storage key and the organization boundary belong on the row that owns
access.

```python
class WorkflowFile(Base, TimestampMixin):
    __tablename__ = "workflow_files"
    id: UUID                       # == the FileRef.file_id that names it
    organization_id: UUID          # FK CASCADE, indexed — the boundary FileRef validation checks
    workflow_run_id: UUID          # FK CASCADE — every FileRef this issue creates is run-scoped
    producing_node_run_id: UUID | None   # FK node_runs, SET NULL — lineage
    storage_path: str              # get_file_storage()'s key, resolved via the deployment's
                                    # backend, never stored per-row (matches ChatFile)
    content_type: str
    byte_size: int
    filename: str | None
```

**Bind-time (Pass 0, mirroring `TableIORef`'s rule):** a literal `FileRef` in
a `config` must resolve to a `WorkflowFile` row whose `organization_id`
matches `ctx`'s, else `GraphValidationError`. Most `FileRef`s are not
literals — a `FileRef` `http.download`/`file.write`/`image.transform`/a
conversion node produces is a `NodeOutputRef` resolved only at dispatch, so
real enforcement is a repository lookup every handler makes first, checking
two things, not one (round 3 of this review: organization equality alone
lets any workflow run as a member of the same organization read a file a
*different* workflow's run produced, by obtaining its UUID, even though
that principal cannot see or run the producing workflow — the run-scoped
ownership `workflow_run_id` already carries on `WorkflowFile` was never
consulted): `workflow_file_repo.get_by_id(db, file_id,
organization_id=ctx.organization_id)` first, then confirm the row's
`workflow_run_id` is either this run's own or present in this run's
`ResourceRef`s (explicitly imported, the same table #1790's foreach
manifests already use) — a file belonging to a different, unimported run
answers `None` exactly as a cross-organization one does. `None` in both
cases is raised as `NotFoundError` — not `AuthorizationError`, so a probe
learns nothing either way, the same non-disclosure `resolve_access` already
gives every lookup here. This is the acceptance criterion's
cross-organization test, extended to cross-run: forge another org's
`file_id`, and separately another run's own-organization `file_id`, into a
bound config and into a
`NodeOutputRef`-resolved input, assert `NotFoundError` both ways. References
grant no access themselves — an id is only useful to a handler holding the
run's own `ctx`.

## `http.download` / `http.upload` — streamed, pinned, sniffed

```python
class HttpTransferConfig(BaseModel):
    url: str
    headers: dict[str, str] = {}
    auth: HttpAuthConfig = HttpAuthConfig(kind="none")      # #1789's shape, reused
    max_redirects: int = Field(default=5, le=10)
    timeout_seconds: int = Field(default=30, le=120)

class HttpDownloadConfig(HttpTransferConfig):
    expected_content_types: tuple[str, ...] | None = None
    max_bytes: int = Field(default=25_000_000, le=200_000_000)

class HttpDownloadOutput(BaseModel):
    file: FileRef
    content_type: str        # sniffed from bytes, never the response header
```

`PinnedAsyncClient` sends one request and does not follow redirects by
design ("the caller walks them, so it can bound them"). `http.request` never
needed to; a download target does (a signed S3 URL, a CDN). So these two
nodes own the loop it doesn't: on a 3xx, `Location` is resolved through the
same `resolve_pinned_url` the transport calls internally, up to
`max_redirects`, each hop still dialled through `PinnedAsyncClient`.

**Streamed, checked as bytes, not headers.** `client.stream(...)`/
`aiter_bytes()`, counting as chunks arrive; `Content-Length` is a hint only,
and exceeding `max_bytes` — with or without one — aborts as
`Failed(code="response_too_large")`, nothing partial saved. The type is
sniffed from bytes (`sniff_image_header`/`sniff_container`,
`app/services/file_storage.py`, extended with PDF/text), refused as
`Failed(code="content_type_mismatch")` against a set `expected_content_types`
— a declared header is never believed alone, `has_format_conflict`'s own
reason. Storage (`get_file_storage().save(...)`, then a `WorkflowFile` row)
happens only after the sniff passes.

`http.upload` is the inverse: `HttpTransferConfig` + `body: FileRef`,
streamed from storage via `BaseFileStorage.open_stream` directly into the
request body, never buffered whole.

**`retry_guarantee`** mirrors #1789: `http.download` is always `GET` →
`"idempotent"`. `http.upload` is `"idempotent"` only with
`idempotency_key_header` set (from the `NodeAttempt`'s own stable key);
otherwise `"at_least_once"`. `Uncertain` reuses #1789's one trigger: a
post-send timeout on a non-idempotent upload is
`Uncertain(detail="request sent; no response received")`.

## `file.read` / `file.write` — UTF-8 text, JSON, CSV

```python
class FileReadConfig(BaseModel):
    parse_as: Literal["text", "json", "csv"] = "text"

class FileReadOutput(BaseModel):
    text: str | None = None
    json_value: Any | None = None
    rows: tuple[dict[str, str], ...] | None = None   # header-keyed

class FileWriteConfig(BaseModel):
    format: Literal["text", "json", "csv"] = "text"
    filename: str | None = None
```

Only the field matching `parse_as`/`format` is populated; a decode failure
(bad UTF-8, malformed JSON, a ragged CSV) is
`Failed(code="file_parse_failed", details={"parse_as"})`, never a truncated
best-effort value. `retry_guarantee` splits by direction: `file.read` is
`"idempotent"` — reading has no side effect to duplicate. `file.write` is
`"at_least_once"`, not `"idempotent"` (round 1 of this review caught the
first draft claiming `idempotent` while its own text said a retry mints a
*fresh* `WorkflowFile` row — minting a new row per attempt is definitionally
not idempotent, and #1788's reconciler treats `idempotent` as "safe to
auto-retry once assuming it converges on the same effect," which a fresh row
per attempt does not). An `at_least_once` write is not wrong to retry, but a
caller downstream of it must not assume exactly one row exists per logical
write; #1793's crash-injection matrix exercises this distinction directly.

## `text.extract` — and the typed OCR refusal

```python
class TextExtractOutput(BaseModel):
    text: str
    source_format: Literal["txt", "json", "csv", "pdf", "docx"]
    page_count: int | None = None
```

TXT/JSON/CSV: UTF-8 decode as-is. DOCX: the same `python-docx` paragraph-join
RAG ingestion already uses. PDF: `pymupdf`'s text layer, page by page.

**A scanned PDF says so.** Before extracting, the handler runs the same
cheap text-layer preflight `documents.py`'s `_needs_ocr` already does — not
the OCR pass — and if any page has no text layer, returns
`Failed(code="text_extraction_needs_ocr", details={"page_numbers": [...]})`.
General OCR is out of scope; the alternative RAG's own comment names as the
failure to avoid (`#550`) is silently indexing a scan as empty text — this
node refuses instead of guessing. A corrupt or encrypted document is its own
code, `Failed(code="document_corrupt")` / `Failed(code="document_encrypted")`,
never the parser's raw exception text.

## Conversions: four narrow node kinds, not one `convert`

Each has a config/IO shape specific to the one pair it converts, matching
`output_schema` being fixed per *definition* — a generic `convert` node would
need a runtime-chosen output shape no `output_schema` can express, and rule 3
(type compatibility) can only check an edge against a schema, not a variable.

- **`convert.csv_to_json`** — `rows` in, `json_value: list[dict[str, str]]`
  out. Pure reshape.
- **`convert.json_to_csv`** — refused as `Failed(code="not_tabular")` unless
  the input is a list of flat objects sharing one key set, never a
  best-effort flatten.
- **`convert.text_to_file`** — `text` in, `file: FileRef` out (`.txt`), the
  pairing for `text.extract`'s output feeding a later write step.
- **`convert.pdf_to_png`** — `file` (PDF) + `pages: tuple[int, ...]` in,
  `images: tuple[FileRef, ...]` out, rendered via `pymupdf` the way
  `documents.py` already rasterizes a page for its own OCR fallback — reused
  rendering, new caller. A page outside the document's count is
  `Failed(code="page_out_of_range")`.

`effect_kind="write"` for the two that mint storage
(`text_to_file`/`pdf_to_png`), `"pure"` for the two reshapes.
`retry_guarantee`: `"idempotent"` for the two pure reshapes,
`"at_least_once"` for `text_to_file`/`pdf_to_png` — the same "mints a fresh
row per attempt" reasoning `file.write` above carries, not `"idempotent"`.

## `image.transform` — bounded before it allocates

```python
class ImageTransformConfig(BaseModel):
    resize: ImageResize | None = None       # width, height, mode: fit|fill|exact
    crop: ImageCrop | None = None
    rotate_degrees: Literal[0, 90, 180, 270] = 0
    output_format: Literal["png", "jpeg", "webp"] = "png"
    quality: int = Field(default=85, ge=1, le=100)

class ImageTransformOutput(BaseModel):
    file: FileRef
    width: int
    height: int
```

`Image.open()` decodes only the header; `.size` is available before any
pixel buffer exists. The handler checks `width * height` against
`CHAT_IMAGE_MAX_PIXELS` (the same setting chat attachments already enforce,
not a second constant) **before** `.load()`/`.resize()`/`.crop()` — a small
file declaring an enormous canvas is `Failed(code="image_too_large",
details={"decoded_pixels", "limit"})` before the full-size buffer exists,
the "check before decode" discipline `config.py` already states, applied
here to a `FileRef` instead of a `ChatFile`. **The same check runs again on
the requested output**, not only the source (round 3 of this review: a
small, valid source image with an enormous `resize.width`/`resize.height`
passed the source-side check and then exhausted memory allocating the
*output* canvas — the cap on decoded pixels said nothing about produced
ones): compute `resize.width * resize.height` from config before calling
`.resize()`, refused the same way if it exceeds the limit. Metadata (EXIF,
ICC) is dropped by never forwarding `image.info` into the write call. `retry_guarantee=
"at_least_once"`, not `"idempotent"` — the transform itself is
deterministic over already-fetched bytes, but its output is a fresh
`WorkflowFile` per attempt like every other write node here, so the same
correction applies.

## `code.python`: two node kinds, not one

**`code.python.simple`** refactors the existing Monty adapter
(`code_execution/_sandbox.py`) for typed JSON IO instead of the free-text
stdout-plus-result string an agent tool call reads. `run_python`'s shape is
built for an LLM reading prose; this node requires the script to assign a
JSON-serializable `output` and returns it typed:

```python
class PythonSimpleConfig(BaseModel):
    code: str                          # versioned with the graph, like any config field
    timeout_seconds: float = Field(default=10.0, le=30.0)
    max_memory_mb: int = Field(default=256, le=512)

class PythonSimpleInput(BaseModel):
    args: dict[str, Any]

class PythonSimpleOutput(BaseModel):
    result: Any
    stdout: str            # clipped, `_sandbox.py`'s own MAX_OUTPUT_CHARS reused
```

A non-JSON-encodable `output` is `Failed(code="python_output_not_json")` —
the acceptance criterion's invalid-output test. Monty has no filesystem or
network, so this stays `effect_kind="pure"`, `retry_guarantee="idempotent"`.

**`code.python.sandbox`** is the full-access path and does not run through
Monty. It opens a `sandboxd` session through the org's registered
`SandboxConnection`, on a **new catalogue entry**, `workflow-python`
(`needs_network: false`, no `git`/`curl`/LibreOffice setup), and — unlike an
interactive agent session — no vault-derived credential and no platform
token is ever staged into it; the session carries only `args` and input
`FileRef` bytes.

```python
class PythonSandboxConfig(BaseModel):
    code: str
    timeout_seconds: float = Field(default=120.0, le=1800.0)
    max_memory_mb: int = Field(default=1024, le=2048)
    max_disk_mb: int = Field(default=512, le=2048)

class PythonSandboxOutput(BaseModel):
    result: dict[str, Any] | None
    stdout_tail: str
    log_file: FileRef                  # full captured output, never inlined
    output_files: tuple[FileRef, ...]
```

**Fitting #1788's dispatch model: poll a deterministic session, not push a
wake.** Approval's `Waiting(reason="approval")` works because a human
decision commits a row this application controls, so the decision itself
inserts the wake via `spawn_after_commit`. `sandboxd` has no such hook —
nothing calls this backend back when a background script finishes. Modelling
this as `Waiting(reason="external_event")` with a bespoke poller would
duplicate `workflow-dispatch-poll` for a signal that must be polled anyway.
The shape that already exists and needs no change to #1786/#1788/#1790 is
`Waiting(reason="retry_backoff")` — the mechanism a retryable `Failed`
already schedules a future dispatch through. Each dispatch derives a session
key from the same string #1788/#1790 mint as `NodeAttempt.idempotency_key`;
**reconnects** if a session for that key exists, checking a completion
marker the launch step wrote; **only if none exists**, stages inputs and
launches the script backgrounded (`nohup ... & echo $! > job.pid; disown`,
so the launching `execute` call returns quickly rather than blocking for the
job's whole run — `SANDBOXD_EXECUTE_TIMEOUT`, 300 s, bounds one call, not the
job). No marker yet → `Waiting(reason="retry_backoff",
resume_token=<NodeRun.id>)`; the next scheduled dispatch repeats the
check-then-launch step, always a reconnect after the first attempt. This is
also the answer to reconnecting after a dispatcher crash: a reconciler retry
is, to the handler, just another dispatch, and check-before-launch makes it
a reconnect automatically — the node's own contract, not the target
system's, is what licenses `retry_guarantee="idempotent"` here.

**Limits.** `timeout_seconds` (capped at 30 minutes) bounds the job's total
wall clock across every backoff cycle, checked against the first
`NodeAttempt.started_at`; exceeding it is
`Failed(code="python_sandbox_timeout")` and the handler closes the session
rather than leaving it for the idle reaper. CPU (2 cores), process count
(512) and `/tmp` (64 MiB) are `sandboxd`'s own per-sandbox ceilings,
inherited as-is; memory is the catalogue entry's `mem_limit`, one setting
per profile like every other runtime. **Disk has no existing per-session
quota in `sandboxd`**, and this issue's `max_disk_mb` check does not add
one — it is detection, not prevention (round 3 of this review: summing
workspace size after the script exits can only refuse the *output*,
letting untrusted code fill the sandbox host's disk for the whole run
first, a real availability risk to whatever else shares that host, whether
or not the eventual output is accepted). Real enforcement needs a
filesystem quota inside `sandboxd`'s own runtime — a size-capped volume or
a disk cgroup per session — which is infrastructure this design doc cannot
add unilaterally; it is a prerequisite for `max_disk_mb` to mean what its
name says, not an implementation detail of this node. Until that lands,
the after-the-fact check stays as a bound on what a node's *output* can
claim to have produced, documented as exactly that and no more. Logs never
land in `NodeAttempt.result` whole, the same "a path, never a payload" rule
`sandbox_operations` already applies to `execute`: a clipped `stdout_tail` in
the typed output, the full log as a `WorkflowFile`-backed `FileRef`.
`effect_kind="write"`, `scopes=frozenset({"sandbox:execute"})` — the scope
the interactive workspace capability's `execute` tool already gates, so a
binding without it is refused at Pass 0 like a missing capability scope.

## Images reach the model as content, never as a URL

`agent.run`'s `AgentRunInput.attachments: tuple[FileRef, ...]` (#1789) must
resolve to real bytes, not a link a hosted model cannot fetch.
`AttachmentRouter._inline_images` already builds exactly the needed object,
`BinaryContent(data=..., media_type=...)`, off a `ChatFile`; this issue adds
the `WorkflowFile` equivalent — `get_file_storage().load(storage_path)` (or
`open_stream`, bounded, for a large one) wrapped the same way — appended to
the `UserContent` list `agent.run`'s handler builds before
`PreparedRun.execute(...)`, never rendered as text in the prompt. A
`FileRef` whose type the target model does not accept is
`Failed(code="unsupported_attachment_type")` at the node, not a silent drop
— the acceptance criterion's "unsupported... models fail clearly."

## The UI describes the runtime and conversion matrix: on the catalog, not a second endpoint

**Decision: `NodeCatalogEntry.description` and the three schemas carry this;
#1791 adds no capability-matrix route.** #1786's catalog already serializes
every `description` and its schemas as JSON Schema, which gives #1787's
palette everything structural — a `Literal["png", "jpeg", "webp"]` renders as
a dropdown with no second lookup. The remaining question is prose ("PDF text
only, a scan needs OCR," "no network," the pixel cap's number), and
`docs/sandbox.md` already solves an identical problem: `runtime_briefing` is
*composed from the catalogue*, not hand-written beside it, so a changed
number cannot go stale in what a reader sees. Node `description`s here are
built the same way — an f-string reading the same `Literal` members,
`CHAT_IMAGE_MAX_PIXELS`, and `workflow-python`'s own fields — so
`text.extract`'s description names its formats and OCR refusal from the same
constants its handler enforces, and `code.python.sandbox`'s names the live
runtime profile rather than a copy that can drift. A second endpoint would
duplicate this or become the thing #1787 actually reads instead of the
catalog.

## Test plan

One contract test per node package (schema round-trip, registered under
`load_builtins()`, a handler call per `NodeResult` variant), mirroring
`test_debug_echo_registered`. Integration: a private-IP download target
refused before connecting; an over-`max_bytes` stream aborted with no
partial `WorkflowFile`; a declared-`image/png` body that is actually HTML
refused by the sniff; a compression-bomb PNG refused before `.load()`; a
scanned PDF refused naming its pages, never emptied; a corrupt DOCX and an
encrypted PDF each their own typed code; `code.python.sandbox` killed after
launch but before the first `Waiting` persists — restart must reconnect, not
launch a second session, asserted by one session existing for the
deterministic key; a timeout test closing the session; a cross-organization
`FileRef` (bound literal and `NodeOutputRef`) refused both ways. The
milestone's worked example — file → foreach → extract/transform → agent →
Python → upsert → report — is built as one fixture graph exercising every
node above inside a `control.foreach` body, reused by #1793.

## Commit order

1. `WorkflowFile` model, repository, migration.
2. `http.download`/`http.upload` — streaming, sniffing, the redirect walk,
   `retry_guarantee`, with SSRF/oversize regression tests in the same commit.
3. `file.read`/`file.write`, `text.extract` (OCR-preflight reuse and its
   refusal test), then the four `convert.*` nodes.
4. `image.transform` — the pixel-cap-before-decode test first.
5. `code.python.simple` — the Monty refactor, independent of the sandbox job.
6. The `workflow-python` catalogue entry, `sandbox_jobs.py` (session-key
   derivation, reconnect-before-launch), then `code.python.sandbox` — the
   crash/reconnect integration test lands with this commit.
7. `agent.run`'s `WorkflowFile`→`BinaryContent` path, extending #1789.
8. Node `description`s composed from the constants their handlers enforce;
   the shared fixture graph for #1793.
