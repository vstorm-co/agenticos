# FA-013 — Complete chat attachment formats (issue #1591)

Design, Codex review, and implementation plan for extending **chat attachment**
upload/processing to cover the eight missing formats and the second XML MIME type.

Branch: `feat/fa013-chat-attachment-formats` (based on `main`).

> Scope note: this is the **chat-attachment** path (`POST /api/v1/files/upload` →
> `FileUploadService` → `AttachmentRouter`), the one that reaches agents **with and
> without a workspace**. It is a separate parser implementation from RAG ingestion
> (`app/services/rag/`), which is out of scope except where we deliberately reuse a
> library it already pulls in.

---

## 1. Current state (what exists today)

### 1.1 The chat path, end to end

| Stage | Location |
|---|---|
| Upload route | `backend/app/api/routes/v1/files.py` — `POST /files/upload`, `GET /files/{id}`, `GET /files/{id}/info` |
| Validation + classification + parsing + persistence | `backend/app/services/file_upload.py` — `FileUploadService` |
| Allowlist, size, classification, storage | `backend/app/services/file_storage.py` — `ALLOWED_MIME_TYPES`, `classify_file`, `IMAGE_MIME_TYPES`, `SPREADSHEET_MIME_TYPES`, `RENDER_SAFE_MIME_TYPES`, `LocalFileStorage` |
| Bounded blocking pool | `backend/app/core/blocking.py` — `run_blocking`, `FILE_IO_MAX_WORKERS` admission gate |
| Prompt/workspace routing | `backend/app/services/attachments.py` — `AttachmentRouter` (**in the 100% coverage gate**) |
| DB row | `backend/app/db/models/chat_file.py` — `ChatFile.file_type` is `String(20)`, no DB enum/CHECK |
| Config | `backend/app/core/config.py` — `CHAT_MAX_UPLOAD_SIZE_MB=10`, `FILE_IO_MAX_WORKERS=8`, `SANDBOX_INLINE_IMAGE_MAX_BYTES=5MiB` |
| Frontend picker | `frontend/src/components/chat/chat-input.tsx` (L436 `accept=…`); proxy `frontend/src/app/api/files/upload/route.ts`; kinds `frontend/src/lib/file-kinds.ts` |

### 1.2 The 11 formats currently reaching an agent usefully

`ALLOWED_MIME_TYPES` actually lists 19 MIME strings, but only 11 of the 19 FA-013
**formats** are covered: DOCX, TXT, PDF, XLSX, JSON, XML (`text/xml` only), HTML, MD,
CSV, PNG, JPEG. (The extra allowlist entries — `text/css`, `text/x-python`,
`text/javascript`, yaml, gif, webp — are code/text/image variants, not new FA-013
formats.)

`classify_file` maps a MIME/extension to one of five `file_type` values —
`image | pdf | docx | spreadsheet | text` — and `parse_content` dispatches:

- `text` → UTF-8 decode
- `pdf` → PyMuPDF (deliberately **not** LiteParse here; see the docstring)
- `docx` → python-docx
- `spreadsheet` → openpyxl, per-sheet tab-separated (`.xlsx`/`.xlsm` only; `.xls` refused)
- `image` → not parsed; sent to the model as `BinaryContent(bytes, mime)`

### 1.3 The eight missing FA-013 formats + XML

**Add:** DOC, XLS, PPTX, MSG, TIFF, ODP, ODS, ODT — and accept `application/xml`
alongside `text/xml`.

### 1.4 Libraries already in the manifest (no new dep needed)

`pymupdf`, **`pillow>=10`**, `python-docx`, `openpyxl`, **`liteparse>=2.14.3`**
(LibreOffice-backed, already used by the RAG `LiteParseParser`; LibreOffice + Tesseract
ship in the backend Dockerfile). RAG's `LITEPARSE_OFFICE_FORMATS` already lists
`.doc/.xls/.pptx/.odp/.ods/.odt`.

---

## 2. Design

> **§5 supersedes three choices below after the Codex round:** MSG uses `olefile`
> (BSD-2), not GPL `extract-msg`; DOC uses a directly-managed, killable `soffice`
> subprocess, not `liteparse`; `validate_upload` gains a `filename`/extension argument.
> The rest of §2 stands. Read §2 for the shape, §4–5 for what changed and why.

### 2.1 Parser / converter per new format

Guiding principle, kept from the existing chat path: **prefer a light, pure-Python,
in-process reader; only shell out to LibreOffice where no such reader exists.** This
keeps the resource-isolation surface (subprocess) as small as possible and keeps the
common formats fast and dependency-light.

| Format | `file_type` | Output to model | Library | In-process? | Notes |
|---|---|---|---|---|---|
| **DOCX** (existing) | `docx` | text | python-docx | yes | unchanged |
| **DOC** | `document` | text | **LibreOffice via `liteparse`** (existing dep) | no (subprocess) | only format with no viable pure-Python reader |
| **XLS** | `spreadsheet` | text (tab-sep sheets) | **`xlrd`** (new) | yes | mirrors the openpyxl output shape for consistency |
| **XLSX** (existing) | `spreadsheet` | text (tab-sep) | openpyxl | yes | unchanged |
| **ODS** | `spreadsheet` | text (tab-sep) | **`odfpy`** (new) | yes | |
| **PPTX** | `presentation` | text (shapes + tables + notes) | **`python-pptx`** (new) | yes | |
| **ODP** | `presentation` | text | **`odfpy`** (new) | yes | |
| **ODT** | `document` | text | **`odfpy`** (new) | yes | |
| **MSG** | `email` | text (headers + body; attachment names listed, not recursed) | **`extract-msg`** (new) | yes | Outlook OLE |
| **TIFF** | `image` | **image** — converted to PNG page(s) | **Pillow** (existing) | yes | multi-page → N PNGs; see §2.4 |
| **XML** (widen) | `text` | text | UTF-8 decode (existing) | yes | just add `application/xml` to the allowlist |

New Python dependencies: **`xlrd`, `odfpy`, `python-pptx`, `extract-msg`** — all
pure-Python, small, permissive-enough licenses (details in §2.7). DOC reuses the
already-present `liteparse`; TIFF reuses the already-present `pillow`.

Rejected alternative (recorded so it is not re-proposed): *route all six office/legacy
formats through `liteparse`* — smallest footprint (1 new dep) and most consistent with
RAG, but (a) makes every PPTX/ODT/ODS/ODP upload depend on a LibreOffice subprocess and
a cold start, (b) changes spreadsheet output from clean tab-separated sheets to
LiteParse markdown (inconsistent with the existing `.xlsx` card/prompt), and (c)
enlarges the subprocess resource-isolation surface from one rare format to six. The
hybrid keeps the fast in-process path for everything a small library can read.

### 2.2 Where the format list changes

- `backend/app/services/file_storage.py`
  - `ALLOWED_MIME_TYPES` — add: `application/msword` (DOC), `application/vnd.ms-excel`
    (XLS), `application/vnd.openxmlformats-officedocument.presentationml.presentation`
    (PPTX), `application/vnd.ms-outlook` (MSG), `image/tiff` (TIFF),
    `application/vnd.oasis.opendocument.presentation` (ODP),
    `application/vnd.oasis.opendocument.spreadsheet` (ODS),
    `application/vnd.oasis.opendocument.text` (ODT), and `application/xml` (XML).
  - `classify_file` — new branches:
    - DOC/ODT → `document`
    - PPTX/ODP → `presentation`
    - XLS/ODS → extend the existing `spreadsheet` branch
    - TIFF → `image` (via an explicit check; **not** added to `IMAGE_MIME_TYPES`, see below)
    - MSG → `email`
  - Introduce `TIFF_MIME_TYPES = {"image/tiff"}`. Keep `IMAGE_MIME_TYPES` (the four
    web-safe raster types) and therefore `RENDER_SAFE_MIME_TYPES` **unchanged** — a
    browser cannot render TIFF inline, so it must continue to be served as a download,
    and inline-to-the-model conversion happens separately (§2.4).
- `backend/app/services/file_upload.py`
  - `parse_content` dispatch extended to the new `file_type`s, keyed on `mime_type`
    (extension fallback) inside each branch where one category has several readers
    (e.g. `spreadsheet` → openpyxl vs xlrd vs odfpy).
  - New private parsers: `_parse_doc_content` (liteparse), `_parse_xls_content` (xlrd),
    `_parse_ods_content`/`_parse_odt_content`/`_parse_odp_content` (odfpy),
    `_parse_pptx_content` (python-pptx), `_parse_msg_content` (extract-msg). Each runs
    under `run_blocking`, catches its own library's errors, logs a warning, returns
    `None` on failure (same contract as the existing parsers).

### 2.3 MIME robustness — the `application/octet-stream` problem

Browsers frequently send `application/octet-stream` (or an empty type) for `.msg`,
`.odp/.ods/.odt`, and sometimes `.doc/.xls`. The current validator rejects anything not
in `ALLOWED_MIME_TYPES`, so those uploads would be refused even though we can parse
them. Design decision:

- **Validate on `(content_type ∈ allowlist) OR (extension ∈ allowed-extension set)`.**
  Add an `ALLOWED_EXTENSIONS` set derived from the format list. This mirrors the
  frontend `accept` list (which already offers both MIME types and extensions) and the
  RAG pipeline, which routes by extension.
- `classify_file` already falls back to extension for docx/spreadsheet; extend the same
  pattern so an `octet-stream` `.pptx` classifies correctly.
- Keep a hard refusal for a genuinely unknown type **and** unknown extension.
- Store the caller-declared `mime_type` as today, but classification/parsing must not
  trust it blindly — extension is the tiebreaker.

### 2.4 TIFF: image output, including multi-page

TIFF is not accepted by the vision APIs (Anthropic/OpenAI accept png/jpeg/gif/webp
only), so a TIFF cannot be sent as `BinaryContent(image/tiff)`. It must be converted to
PNG **at the point it is shown to the model**, and multi-page TIFFs must contribute more
than page one.

Chosen approach — convert in `AttachmentRouter` (keeps the original TIFF on disk for
download/workspace, and is the only place that knows how many images a turn may carry):

- `ChatFile.file_type = "image"`, `parsed_content = None`, stored bytes = original TIFF.
- A new helper `tiff_pages_to_png(data, *, max_pages) -> list[bytes]` (Pillow
  `ImageSequence`) converts up to `CHAT_TIFF_MAX_INLINE_PAGES` pages to PNG.
- `AttachmentPlan.inline` changes from `BinaryContent | None` to
  `list[BinaryContent]` (empty list = none). `build_prompt` already accumulates a list,
  so this is a small, well-contained refactor. The single-image path returns a
  one-element list.
- `_inline_image` becomes `_inline_images` and returns the PNG-per-page list for TIFF
  and the single as-is `BinaryContent` for the four web-safe types.
- When pages are truncated at the cap, the file's reference text names the total page
  count and how many were shown, so the model knows the rest exist. For an agent **with
  a workspace**, the original multi-page TIFF is on disk and it can open the remaining
  pages itself.
- Per-page PNGs are individually bounded by `SANDBOX_INLINE_IMAGE_MAX_BYTES`; a page
  that exceeds it after conversion is downscaled by Pillow before encoding (bounded
  longest edge) rather than dropped.
- **Limitation, documented:** a scanned TIFF yields an image, not OCR text — the chat
  path has no OCR (same limitation as a scanned PDF).

### 2.5 Attachment routing (`attachments.py`) changes — coverage-gated

`app/services/attachments.py` is in the 100% platform coverage gate, so every new
branch needs a test. Changes:

- `AttachmentPlan.inline: list[BinaryContent]` (was `BinaryContent | None`).
- `_inline_image` → `_inline_images` returning a list; TIFF branch calls
  `tiff_pages_to_png`.
- `_text_sibling` predicate broadened from `{"pdf","docx","spreadsheet"}` to **any
  text-bearing binary**: `parsed_content` present and `file_type not in {"text","image"}`
  — so `document`, `presentation` and `email` also get the `.txt` sibling written beside
  the original for a workspace that cannot read the source.
- `_referenced`/`_pasted`/`_unreadable` unchanged in shape; they already key off
  `file_type` and `parsed_content`.

### 2.6 Resource isolation & bounding for conversions

- All parsing already runs on the **dedicated bounded pool** (`run_blocking`,
  `FILE_IO_MAX_WORKERS` admission gate) — new parsers inherit this; a burst cannot
  starve the loop's bcrypt/DNS threads.
- Input size is already bounded by `CHAT_MAX_UPLOAD_SIZE_MB` (10 MB), enforced
  server-side after read.
- **DOC/LibreOffice specifics:**
  - New `CHAT_CONVERT_TIMEOUT_SECONDS` config (default 60s) passed to the liteparse call
    so a single-request office conversion cannot hang the pool worker indefinitely
    (RAG's default is 600s, far too long for an interactive upload).
  - Each conversion writes the bytes to a `TemporaryDirectory` and runs LibreOffice with
    a **per-conversion user-profile dir** (LibreOffice serializes/locks when two
    processes share one profile). Rely on liteparse's own temp handling if it already
    isolates the profile; otherwise set `HOME`/`-env:UserInstallation` per call. This is
    called out as a risk to verify against the installed liteparse version.
  - If LibreOffice is absent (non-Docker dev), DOC parses to `None` → the model is told
    the text could not be extracted (graceful, same as RAG's documented degradation).
- Multi-page TIFF is bounded by `CHAT_TIFF_MAX_INLINE_PAGES` and per-page byte cap.
- No new unbounded recursion: MSG attachments are **listed, not extracted** (a `.msg`
  can nest `.msg`s; recursing is a zip-bomb-shaped risk we decline).

### 2.7 Dependencies — footprint & licensing

| Dep | Purpose | License | Footprint |
|---|---|---|---|
| `python-pptx` | PPTX text | MIT | pure-Python; pulls `lxml` (already transitively present via others) + `XlsxWriter` |
| `odfpy` | ODT/ODS/ODP | dual **Apache-2.0 / GPL-2.0** (use under Apache-2.0) | pure-Python, tiny |
| `xlrd` | legacy XLS | BSD-3-Clause | pure-Python, tiny |
| `extract-msg` | Outlook MSG | BSD-2-Clause | pure-Python; pulls `olefile`, `tzlocal`, `compressed-rtf` |
| `pillow` | TIFF→PNG | HPND (permissive) | **already present** |
| `liteparse` | DOC via LibreOffice | (existing) | **already present** |

- Note the `odfpy` dual license explicitly; the Apache-2.0 option keeps the platform
  permissive. If legal prefers to avoid it, the fallback is routing ODT/ODS/ODP through
  `liteparse` (LibreOffice), at the cost of the subprocess path for those three.
- Each new dep must be declared in `backend/pyproject.toml`; `deptry` requires that
  every declared distribution is imported under `app/`. The parsers import them directly,
  so no `DEP002` ignore is needed. `extract-msg`/`python-pptx` pull transitive
  distributions — verify `deptry` is satisfied and the lockfile resolves.

### 2.8 Frontend

- `frontend/src/components/chat/chat-input.tsx` — extend the `accept` attribute with the
  new MIME types **and** extensions: `application/msword,.doc`,
  `application/vnd.ms-excel,.xls`, `…presentationml.presentation,.pptx`,
  `application/vnd.ms-outlook,.msg`, `image/tiff,.tiff,.tif`,
  `…opendocument.presentation,.odp`, `…opendocument.spreadsheet,.ods`,
  `…opendocument.text,.odt`, and `application/xml` (text/xml already implied by the
  server). Extensions matter because the OS often supplies `octet-stream` for these.
- `frontend/src/lib/file-kinds.ts` — already maps `tiff/xls/ods/doc/odt/pptx`. Add
  `odp → document` and (optionally) a mapping for `.msg`. No new `FileKind` is required
  (`msg` can fall to `unknown` → icon + download); a nicer icon is a small, optional
  follow-up. TIFF already resolves to `image`.
- Client size check already reads `CHAT_MAX_UPLOAD_SIZE_MB` — unchanged.
- No new `FileViewer` behavior: office/email formats are "known, not showable" (icon +
  download), which `file-kinds.ts` already models; TIFF is downloaded, not rendered
  inline (server refuses to type it render-safe), consistent with the CSP rule.

### 2.9 Documentation

- `docs/file-processing.md` — the **Supported file types** table (chat section) gains
  the eight formats and the TIFF/office/email/`application/xml` rows; update the "where
  an attachment goes" table for `document`/`presentation`/`email`/TIFF; document the
  limitations (scanned PDF/TIFF → no OCR; DOCX/office tables flattened; DOC/office needs
  LibreOffice; MSG attachments listed not extracted). Update the DOC/office note that the
  chat path now uses liteparse for DOC only.
- `docs/reference/capabilities.md` / `docs/channels.md#files` if they enumerate accepted
  types.
- `scripts/docs_drift.py` trigger map — the Stop hook is a reminder, not a gate; ensure
  the page above is updated in the same change.

---

## 3. Risks

1. **Multi-page TIFF token/cost blow-up** — N pages × PNG inline is expensive. Mitigated
   by `CHAT_TIFF_MAX_INLINE_PAGES` and per-page byte cap; agents with a workspace read
   the rest from disk. Scanned TIFF has no OCR (documented).
2. **`AttachmentPlan.inline` list refactor touches gated code** — must fully cover the
   new branches in `test_attachments.py`.
3. **DOC/LibreOffice** — cold start latency inside the upload request, single-instance
   profile locking on concurrency, absence outside Docker. Bounded by timeout +
   per-conversion profile; graceful `None` when unavailable.
4. **MSG MIME variance** (`application/vnd.ms-outlook` vs `application/octet-stream` vs
   `application/x-ole-storage`) — handled by the extension-fallback validation (§2.3).
5. **Malformed office/OLE files** — each parser catches its library's exceptions →
   `None` → the model is told the text could not be extracted; the upload itself still
   succeeds (a parse failure is not an upload failure, matching today's PDF/docx
   behavior). Oversized/unknown are refused up front.
6. **DOCX/spreadsheet tables** flatten to tab-separated / newline text (existing
   limitation, now documented and extended to the new office formats).
7. **`odfpy` GPL/Apache dual license** — use under Apache-2.0; fallback to liteparse if
   legal objects.
8. **Coverage gate contract** — no new *module* is added to the platform layer, so
   `[tool.coverage.run] include` / `[[tool.ty.overrides]] include` need no edit; only
   existing gated modules (`attachments.py`) gain branches that must hit 100%.

---

## 4. Codex review

`codex exec --sandbox read-only` (the default `gpt-5.4-mini` is unusable on this
account and the models cache errored on an `unknown variant "max"`; re-run pinned to
`-m gpt-5.5 -c model_reasoning_effort=high`, which succeeded). Findings, verbatim
severity:

1. **Critical — `extract-msg` license.** PyPI metadata lists `extract-msg` as **GPL
   (GPLv3)**, not BSD-2. A release blocker for a permissive project without explicit
   legal sign-off.
2. **High — extension-fallback validation under-specified.** `validate_upload(content_type,
   size)` has no filename/extension, and the channel preflight
   (`channels/attachments.py`) calls it with only `mime_type` **before download**.
   Without a signature change to every caller, `application/octet-stream` `.msg/.odt/.xls`
   still fails.
3. **High — TIFF conversion not safely bounded.** Checking PNG size *after* Pillow has
   decoded attacker-controlled bytes is too late; compressed size is not a memory bound.
   Pillow documents decompression bombs, CPU exhaustion, TIFF IFD complexity and metadata
   leakage. Need pixel/dimension/page limits before/during decode, treat
   `DecompressionBomb*` as failure, strip metadata.
4. **High — DOC/LibreOffice timeout claim is false.** RAG's `LiteParseParser` itself notes
   `wait_for` bounds only how long the request *waits*, not how long the thread/subprocess
   keeps running. Need a concrete subprocess kill + profile-isolation mechanism, or proof
   liteparse kills LibreOffice.
5. **High — `file_type="image"` for TIFF leaks into browser UI.** Frontend `kindFor`
   (message-item) and `attachment-card` render any `image/*`/`file_type==="image"` as an
   inline thumbnail whose `src` is the download URL — which serves raw TIFF the browser
   cannot draw → broken thumbnail. UI must distinguish web-renderable images from
   model-convertible ones.
6. **High — parsed text expansion not capped.** The no-workspace path pastes full
   `parsed_content`; a small ZIP/OLE upload can expand to very large text. Add a
   server-side extracted-text cap + truncation notice before storing/pasting.
7. **Medium — `_can_parse` too coarse.** Broadening siblings to "all parsed binaries"
   wrongly skips the `.txt` sibling for MSG on a `lit` runtime, since `lit` reads office
   formats but not MSG.
8. **Medium — "pure Python, small" understates attack surface.** `python-pptx` pulls
   `lxml`/Pillow/XlsxWriter; ODF/PPTX are ZIP+XML needing zip-member/expanded-size
   limits; `odfpy` is old and dual-licensed.
9. **Medium — test strategy missing.** §4–6 were placeholders; enumerate the matrix
   (MIME+ext incl. octet-stream, dispatch, malformed, real fixtures, DOC absent/timeout
   mocked, TIFF multipage/cap/downscale/failure, frontend accept + TIFF non-thumbnail,
   channel preflight).
10. **Medium — parser edge cases.** XLS dates/formula caches/password; MSG HTML-vs-plain-
    vs-RTF body, encrypted/signed, header normalization, embedded attachments.

Overall: direction fits the architecture, but not approvable until license, validation
API, TIFF/DOC isolation, text caps, and frontend TIFF behavior are resolved.

---

## 5. Resolutions — accepted / rejected (these amend §2)

**Accepted (design changed):**

- **#1 (Critical) extract-msg license — ACCEPTED.** Drop `extract-msg` (GPLv3). Parse
  MSG with a small in-house reader over **`olefile`** (BSD-2-Clause, tiny) reading the
  standard MAPI property streams: subject `__substg1.0_0037001F/001E`, plain body
  `__substg1.0_1000001F/001E`, sender `__substg1.0_0C1A001F`, recipients from the
  `__recip_version1.0_#…` storages, date from `__properties_version1.0`. Prefer the
  plain-text body stream; fall back to HTML (`1013`) stripped of tags; do **not** parse
  RTF (avoids `compressed-rtf`). If legal accepts GPLv3 or a company CLA exists,
  `extract-msg` remains an option — but the plan assumes the olefile route. (`msg-parser`,
  MIT, is a documented fallback if the in-house reader proves fragile.) `olefile` is
  BSD-2 and likely already transitive; add it explicitly.
- **#2 (High) validation signature — ACCEPTED.** Change
  `validate_upload(content_type, size)` → `validate_upload(content_type, size, filename)`
  and validate on `(mime ∈ allowlist) OR (ext ∈ ALLOWED_EXTENSIONS)`. Update **all three
  callers**: `FileUploadService.upload` (has `filename`), and both
  `channels/attachments.py` call sites (have `attachment.filename`). This is the concrete
  API change §2.3 hand-waved.
- **#3 (High) TIFF decode safety — ACCEPTED.** Before decoding: set a per-conversion
  Pillow `Image.MAX_IMAGE_PIXELS` guard and register `DecompressionBombError`/`Warning`
  as errors (turn into a caught failure → `None`/skip); count frames with
  `n_frames`/`ImageSequence` lazily and cap at `CHAT_TIFF_MAX_INLINE_PAGES` before
  decoding all of them; reject any frame over a max-dimension bound; `img.load()` inside
  the try; re-encode as PNG **without** the source metadata (no EXIF/ICC passthrough).
  Runs on the file pool (already off-loop).
- **#4 (High) DOC isolation — ACCEPTED, library choice changed.** Do **not** route DOC
  through `liteparse` (no kill hook; converts via PDF). Instead add a small
  `libreoffice_convert(data, target="txt") ` helper that invokes `soffice --headless
  --convert-to "txt:Text" --outdir <tmp> <tmp/in.doc>` as a **managed subprocess** with
  `asyncio.create_subprocess_exec`, an explicit `CHAT_CONVERT_TIMEOUT_SECONDS` (default
  60s) and **`proc.kill()` on `TimeoutError`** (plus process-group kill so a hung child
  dies), and a **per-call profile** via `-env:UserInstallation=file://<tmp>/profile` so
  concurrent conversions do not hit LibreOffice's single-instance lock. This removes the
  new-dependency-free reliance on liteparse for chat and gives the real bound Codex asked
  for. Absent `soffice` → helper returns `None` → graceful "text could not be extracted".
  (This helper is the one subprocess in the whole feature; everything else is in-process.)
- **#5 (High) frontend TIFF — ACCEPTED.** Align the frontend "renderable image" decision
  with the backend `RENDER_SAFE_MIME_TYPES` (png/jpeg/gif/webp only). In
  `file-kinds.ts`, stop mapping `tiff`/`image/tiff` to the inline-renderable `image`
  kind; in `message-item.tsx` `kindFor` and `attachment-card.tsx`, gate the inline
  thumbnail on render-safety, not on `file_type==="image"`/`image/*`. TIFF then shows as
  a file card with an icon + download (matching the server, which serves it as a
  download), while the **model** still receives the converted PNG(s). Add a small
  frontend test for "TIFF is not thumbnailed".
- **#6 (High) parsed-text cap — ACCEPTED.** Add `CHAT_PARSED_TEXT_MAX_CHARS` (default e.g.
  1_000_000). Truncate `parsed_content` with an explicit `\n…[truncated N of M chars]`
  marker in `parse_content` before it is stored, previewed, pasted or written as a
  sibling. Protects the no-workspace paste path and the DB column from a ZIP/OLE
  expansion bomb.
- **#7 (Medium) sibling predicate — ACCEPTED, refined.** Sibling is written when
  `parsed_content` is present and `file_type ∈ {pdf, docx, spreadsheet, document,
  presentation, email}`, **skipped** only when `_can_parse and file_type ∈ LIT_READABLE`
  where `LIT_READABLE = {pdf, docx, spreadsheet, document, presentation}` — `email` (MSG)
  always gets the sibling because `lit` cannot read `.msg`.
- **#8 (Medium) attack surface / zip bombs — ACCEPTED.** Correct the dep footprint notes
  (lxml already present; python-pptx pulls XlsxWriter). For ODF/PPTX (ZIP): bound the
  archive — reject if any member's uncompressed size or the total exceeds a cap, and rely
  on the `CHAT_PARSED_TEXT_MAX_CHARS` cap as backstop. odfpy age/license noted (§2.7,
  risk #7).
- **#9 (Medium) tests — ACCEPTED.** Full matrix in §6.4.
- **#10 (Medium) parser edge cases — ACCEPTED, specified.** XLS via `xlrd` with
  `formatting_info=False`; convert dates via `xldate_as_datetime`; password-protected /
  xlsb → caught → `None`. MSG: prefer plain body, else tag-stripped HTML; encrypted/signed
  → caught → `None`; recipients/sender normalized to `Name <addr>`; embedded attachments
  **listed by name only** (no recursion). PPTX: shapes text + table cells + slide notes.

**Rejected / deferred (with reason):**

- **Full per-image sandbox (separate process/uid) for Pillow** — deferred. Codex cites
  Pillow's "sandbox image processing" advice, but the platform has no per-call process
  sandbox for the existing image path either, and introducing one is out of scope for
  this issue. Mitigation taken instead: pixel/dimension/frame caps + bomb-as-error +
  the bounded file pool. Recorded as a possible follow-up.
- **Routing ODT/ODS/ODP through LibreOffice to dodge `odfpy`'s license** — rejected as
  primary; kept as the documented fallback if legal objects to Apache-2.0/GPL dual
  licensing. Pure-Python `odfpy` avoids six more formats hitting the subprocess.

---

## 6. Implementation plan

Ordered, each step independently verifiable. New/changed config lands first so parsers
can read it; frontend and docs last.

### 6.1 Config (`backend/app/core/config.py`)
1. Add settings: `CHAT_CONVERT_TIMEOUT_SECONDS: int = 60` (gt=0),
   `CHAT_TIFF_MAX_INLINE_PAGES: int = 10` (gt=0),
   `CHAT_PARSED_TEXT_MAX_CHARS: int = 1_000_000` (gt=0). Document each near the existing
   `CHAT_MAX_UPLOAD_SIZE_MB`.

### 6.2 Backend — allowlist, classification, validation (`file_storage.py`)
2. Extend `ALLOWED_MIME_TYPES` with the nine MIME strings in §2.2 (incl. `application/xml`).
3. Add `ALLOWED_EXTENSIONS: set[str]` (doc, xls, pptx, msg, tiff, tif, odp, ods, odt, +
   the existing set) and `TIFF_MIME_TYPES = {"image/tiff"}`. Leave `IMAGE_MIME_TYPES` and
   `RENDER_SAFE_MIME_TYPES` unchanged.
4. Extend `classify_file` → new `file_type`s `document`, `presentation`, `email`; TIFF →
   `image`; XLS/ODS join `spreadsheet`. Route by mime with extension fallback.

### 6.3 Backend — parsers & dispatch (`file_upload.py` + new helper)
5. Change `validate_upload` signature to include `filename`; implement mime-or-extension
   acceptance; update the docstring.
6. New module `backend/app/services/office_convert.py` (thick-ish helper, not a route):
   `libreoffice_convert(data: bytes, *, suffix: str, timeout: float) -> str | None` — the
   managed `soffice` subprocess (§5 #4). One place owns the temp dir, profile, timeout,
   and kill. (Async: uses `asyncio.create_subprocess_exec`; called from `parse_content`
   via `await`, not `run_blocking`, since it is already async.)
7. New in-process parsers in `FileUploadService` (each on `run_blocking`, catch→warn→None,
   then apply the `CHAT_PARSED_TEXT_MAX_CHARS` truncation centrally in `parse_content`):
   `_parse_doc_content` (→ office_convert), `_parse_xls_content` (xlrd),
   `_parse_ods_content` / `_parse_odt_content` / `_parse_odp_content` (odfpy),
   `_parse_pptx_content` (python-pptx), `_parse_msg_content` (olefile MAPI reader).
8. Extend `parse_content` dispatch for `document | presentation | email` and the widened
   `spreadsheet`; apply the truncation cap to every returned string once, here.

### 6.4 Backend — attachment routing (`attachments.py`, coverage-gated 100%)
9. `AttachmentPlan.inline: list[BinaryContent]`; update `build_prompt` (already list-based)
   and every `AttachmentPlan(...)` construction.
10. `_inline_image` → `_inline_images(chat_file, data) -> list[BinaryContent]`; TIFF branch
    calls a new `tiff_pages_to_png(data, *, max_pages, max_bytes)` (Pillow, bomb-guarded,
    metadata-stripped, per-page downscale). Non-TIFF images return a one-element list.
11. TIFF reference text names total vs shown page count when truncated.
12. Broaden `_text_sibling` / `_sibling_present` / `_write_extracted_text` per §5 #7
    (`LIT_READABLE`; email always gets a sibling).

### 6.5 Backend — dependencies (`pyproject.toml`)
13. Add `xlrd`, `odfpy`, `python-pptx`, `olefile`; run `uv lock`. Confirm `deptry`
    passes (each imported under `app/`; no `DEP002` ignore expected). Note licenses in the
    PR body.

### 6.6 Frontend
14. `chat-input.tsx` — extend `accept` with new MIME types **and** extensions (§2.8).
15. `file-kinds.ts` — remove `tiff` from the inline-`image` mapping (make it a
    non-renderable/download kind); add `odp → document`; consider `msg`. Keep the
    render-safe set aligned with the backend.
16. `message-item.tsx` `kindFor` + `attachment-card.tsx` — gate the inline thumbnail on
    render-safety, not `file_type==="image"` / `image/*`.

### 6.7 Documentation
17. Update `docs/file-processing.md` (supported-types table, routing table, limitations:
    scanned PDF/TIFF no OCR, office/DOCX tables flattened, DOC needs LibreOffice, MSG
    attachments listed not extracted, multi-page TIFF page cap). Touch
    `docs/reference/capabilities.md` / `docs/channels.md#files` if they list types. Run
    `make docs-build` (--strict).

### 6.8 Tests (§ maps to Codex #9/#10)

**Backend unit (`backend/tests/`, anyio):**
- `test_file_validation.py` (new/extend `test_chat_upload_limit.py`): allow/deny matrix —
  each new MIME accepted; each new **extension with `application/octet-stream`** accepted;
  a genuinely unknown mime+ext refused; oversize refused; XML accepted for both `text/xml`
  and `application/xml`.
- `test_file_classification.py`: every new mime/extension → expected `file_type`
  (incl. octet-stream + extension).
- `test_attachment_parsers.py` (new): real fixtures for DOC, XLS, PPTX, ODP, ODS, ODT, MSG
  under `tests/fixtures/` — assert useful text extracted; malformed bytes → `None`
  (no raise); `CHAT_PARSED_TEXT_MAX_CHARS` truncation adds the marker.
- DOC path: mock `soffice` **absent** → `None`; mock timeout → subprocess killed and
  `None` (assert kill called); success path via a tiny generated `.doc` or a mocked
  converter.
- `test_tiff_attachment.py` (new): single-page TIFF → one PNG BinaryContent; **multi-page**
  TIFF → N PNGs capped at `CHAT_TIFF_MAX_INLINE_PAGES` with the "shown X of Y" note;
  decompression-bomb TIFF → caught (no OOM, skipped/failed cleanly); oversized page
  downscaled.
- `test_attachments.py` (extend, **100% gate**): `AttachmentPlan.inline` list for every
  branch — no-workspace TIFF, workspace TIFF (+ original written), `document`/`presentation`/
  `email` sibling written, `email` sibling written even when `_can_parse` true, refused
  write, unreadable.
- `test_spreadsheet_attachment.py` (extend): XLS + ODS produce the same tab-separated shape
  as XLSX; date cells rendered; password-protected XLS → `None`.
- Channel: extend `test_channel_attachments.py` — a `.odt`/`.msg` arriving as
  `application/octet-stream` passes preflight via the new filename arg.

**Backend integration (`backend/tests/integration/`, real Postgres):**
- Upload → `ChatFile` row for a new format has correct `file_type`, `mime_type`,
  `parsed_content` (or NULL for TIFF); ownership/download unchanged.

**Frontend (`frontend/`, vitest, 100%/97.5% gate on touched dirs):**
- `chat-input.test.tsx`: new extensions/MIME present in `accept`; a new format passes the
  client size check.
- `file-kinds.test` (extend if present): `image/tiff`/`.tiff` is **not** the inline
  `image` kind; `.odp` → document.
- `message-item` / `attachment-card` test: a TIFF attachment renders a file card, not an
  `<img>` thumbnail; a PNG still renders a thumbnail.

**Verification before push:** `make lint`, `make test` (backend + platform 100% gate),
`make test-frontend-cov`, `make db-check` (no schema change expected — `file_type` is a
free `String(20)`, so **no migration**), `make docs-build`. Report any unavailable check.

### 6.9 Out of scope / follow-ups
- Per-process image-decode sandbox (deferred, §5).
- OCR for scanned PDF/TIFF in chat (documented limitation; RAG has LiteParse OCR).
- MSG RTF-body decoding and embedded-attachment extraction.
- A dedicated "email"/"presentation" frontend icon polish.
