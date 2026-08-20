# File Processing

This document covers how files are handled in two contexts: chat file uploads,
which belong to the person who made them, and RAG document ingestion, which
belongs to a collection and is gated on
[who may reach it](#who-may-reach-a-collection).

## Chat File Uploads

When a user uploads a file in the chat interface, the following pipeline runs:

### Flow

```
1. Upload     POST /api/v1/files/upload
               |
2. Validate    Check MIME type against allowed list + enforce size limit
               |
3. Classify    Determine file_type: "image", "pdf", "docx", "spreadsheet", "text"
               |
4. Parse       Extract text content (images skip this step)
               |
5. Store       Save file to media/{user_id}/ via FileStorageService
               |
6. Record      Create ChatFile row in database
               |
7. Link        When message is sent, ChatFile is attached via message_id FK
               |
8. Display     Composer shows a card per attachment: name, excerpt, type, size
```

The upload response carries a `preview` — the first three lines of the extracted
text, bounded at 240 characters — so the card can show what is *in* the file
rather than only what it is called. The browser cannot derive it: a PDF is bytes
until this service has parsed it, and the client holds an id and a filename once
the upload has answered. It is `null` for an image and for a file no parser could
read, and a card with no excerpt shows its thumbnail or its name alone.

### The whole page is the drop target

A file dragged over the chat is accepted **anywhere on it**, not onto the
composer. The composer was the only target, which made attaching something a game
of hitting a strip a few centimetres tall — and missing it was not a no-op: the
browser's default for a dropped file is to *open* it, so the tab navigated away
from the conversation and whatever was half-typed in it. The same
`preventDefault` that lets the page take the file is what stops the browser taking
it, so listening on the window fixes both halves at once.

While a file is over the page, an overlay covers it: the ground blurred, a dashed
card in the middle, and the per-file size limit written on it — a 60MB video
refused *after* the drag is a round trip nobody needed to make. It is portalled to
the body rather than positioned from the composer, because `fixed` is measured
against the nearest transformed ancestor and one `backdrop-blur` on a wrapper
above would quietly shrink the overlay to a corner.

Two things it deliberately does not do. A drag carrying anything **other** than
files — selected text, a link, one of the app's own draggable rows — is left
entirely alone, not even prevented. And nothing is accepted while the composer is
disabled: an archived conversation, a run waiting on an approval. The overlay not
appearing is what says so.

### A long paste is a file

Pasting more than **2000 characters** into the composer uploads the text as
`pasted-<date>.txt` instead of inserting it. The textarea is left untouched, so
the question gets typed beside the thing it is about, and the transcript holds an
attachment rather than one enormous bubble.

The threshold is the whole of the design. Somebody who pastes a paragraph and
presses enter meant that to *be* the message, so it sits above anything a person
would paste as a question — roughly 350 words — and below any document. Under it
nothing changed: the text lands in the textarea as it always has.

After that it is an ordinary `text/plain` attachment and everything below applies
to it unchanged, which is the point: an agent with a workspace gets the paste as
a file it can open, and one without gets the text in its prompt.

### Supported File Types

| Category | MIME Types | Extensions | Processing |
|----------|-----------|------------|------------|
| **Images** | image/jpeg, image/png, image/webp, image/gif | .jpg, .png, .webp, .gif | Stored as-is. Sent to LLM as `BinaryContent` for vision analysis. |
| **PDF** | application/pdf | .pdf | Text extracted via configured PDF parser. Appended to prompt as context. |
| **DOCX** | application/vnd.openxmlformats-officedocument.wordprocessingml.document | .docx | Paragraphs extracted via `python-docx`. Appended to prompt as context. |
| **Spreadsheet** | …spreadsheetml.sheet, …ms-excel.sheet.macroEnabled.12 | .xlsx, .xlsm | Every sheet read via `openpyxl`, named, rows tab-separated. Appended to prompt as context. `.xls` is refused — a different format needing a different reader. |
| **Text** | text/plain, text/markdown | .txt, .md | UTF-8 decoded directly. Appended to prompt as context. |

### Where an attachment goes depends on the agent

The "appended to prompt" column above is what happens to an agent with **no
workspace**, and it is the whole file, on every turn. A two-hundred page report
costs its full token weight when the user asks the first question and again when
they ask "and what about March"; a fifty-megabyte CSV cannot be attached at all.

An agent with the [`sandbox` capability](reference/capabilities.md#files-shell)
gets the file instead of the text:

| Attachment | No workspace | With a workspace |
|---|---|---|
| text, csv, md, json | parsed text pasted inline | written to `/uploads/`, message carries a reference and a 20-line head |
| pdf, docx, spreadsheet | parsed text pasted inline | the original **and** a `.txt` beside it; reference |
| image | `BinaryContent` | `BinaryContent` **and** written; reference names the path |

**A spreadsheet in a workspace is not a spreadsheet an agent can open**, which is
why it is parsed here rather than handed over as bytes. `run_python` has no
filesystem — it is for arithmetic — the workspace shell has no spreadsheet library,
and `read_file` on a zip of XML returns mojibake. The `.txt` beside the original is
the readable half, exactly as it is for a PDF. Accepting the upload without parsing
it would reach an agent with a workspace as unreadable bytes and an agent without
one as nothing at all, which is worse than the refusal it replaced.

The reference is what the model actually reads:

```
Attached file: raport.csv (/uploads/3f2a1b9c-raport.csv, 2.4 MB, text)
First 20 lines:
month,total
jan,10
...
```

Enough to tell a sales export from a log and to see the column names — which is
what the model needs in order to decide whether reading the rest is worth a tool
call. The file has stopped being context and become data.

Four things about it are deliberate:

- **Images go both ways.** The model must still *see* the picture — that is what
  a multimodal model is for, and a path string is not a substitute — and it must
  also be able to resize or crop it, which needs bytes on a filesystem. Above
  `SANDBOX_INLINE_IMAGE_MAX_BYTES` only the file is kept, because past that point
  paying for the bytes twice stops being worth it.
- **A PDF gets both halves.** The bytes are what a person asked to be given; the
  text this platform already extracted is the half a shell can actually read.
- **The same file is written once.** The path is derived from the `ChatFile` id,
  so re-attaching it on turn five resolves to the path it already has — an upload
  costs one write, not one per turn for the rest of the conversation.
- **The filename is not trusted.** `../../etc/passwd` becomes `etc_passwd`; two
  files called `report.csv` cannot overwrite each other.

A file that cannot be stored — a full workspace — falls back to the inline path
rather than vanishing, and one the file store cannot load is skipped rather than
failing the turn: the person asked a question, and answering without the
attachment beats not answering.

Routing happens in `app/services/attachments.py`, called from the chat runner
rather than from each surface. It has to be there: where a file goes depends on
whether the agent has a workspace, and that is decided by `prepare`, which has
not run when a surface is assembling its prompt.

### PDF Parsing (Chat)

Chat attachments are read with **PyMuPDF**, and that is not configurable. An
attachment belongs to no collection, so there is no stored configuration to read
a parser choice from.

The `CHAT_PDF_PARSER` variable that used to select between three parsers is
gone. Both alternatives were wrapped in `except Exception: return
self._parse_pdf_pymupdf(data)`, so a deployment setting it to `llamaparse` or
`liteparse` had been silently using PyMuPDF anyway — and the LiteParse branch
could not have worked at all, calling a `parse_async` method the binding does
not define.

### Size Limits

- Maximum attachment size: `CHAT_MAX_UPLOAD_SIZE_MB` (default: **10 MB**). This is
  the section's own limit — a chat attachment is refused by this number, not by the
  knowledge base's larger `MAX_UPLOAD_SIZE_MB`, and the two are separate settings
  because an attachment to an agent with no workspace is pasted whole into the prompt
  while a knowledge-base document is chunked and embedded.
- A knowledge-base document is capped by `MAX_UPLOAD_SIZE_MB` (default: **50 MB**)
  instead.
- The whole request body is capped above both, at the larger of them plus a multipart
  allowance, so raising either ceiling raises that with it.
- The limit is enforced server-side after reading the file content. The browser's own
  check is `NEXT_PUBLIC_CHAT_MAX_UPLOAD_SIZE_MB`, which should be set to match: too
  high and the composer accepts a file the API refuses, too low and it refuses one the
  API would take.

### Storage

Files are saved by `FileStorageService` to the `media/` directory:

```
media/
  {user_id}/
    document.pdf
    screenshot.png
    ...
```

### ChatFile Model

The `ChatFile` database model tracks uploaded files:

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `user_id` | UUID/FK | Owner (used for access control) |
| `filename` | String | Original filename |
| `mime_type` | String | MIME type (e.g. `application/pdf`) |
| `size` | Integer | File size in bytes |
| `storage_path` | String | Relative path in storage |
| `file_type` | String | Classified type: `image`, `pdf`, `docx`, `spreadsheet`, `text` |
| `parsed_content` | Text | Extracted text content (NULL for images) |
| `message_id` | UUID/FK | Linked message (set when message is sent) |
| `created_at` | DateTime | Upload timestamp |

### Ownership & Access

- Only the file owner can download their files (`GET /files/{id}`).
- The `FileUploadService.get_user_file()` method compares `chat_file.user_id`
  against the requesting user's ID. Returns `NotFoundError` on mismatch.
- **Ownership is the whole rule, and nothing widens it.** No permission, no
  organization role and no grant reaches another person's chat file through this
  API — unlike a collection, which a grant can open up. The comparison is against
  `user_id` and there is no second branch to hold a wider case.
- **The link step takes the same rule.** A message attaches only the sender's
  own *unlinked* files: an id naming another user's file, or one already on a
  message, is refused rather than silently applied — so a turn can neither
  render a stranger's filename nor pull an attachment off the message it
  already hangs on.

## RAG Document Ingestion

When documents are ingested into the RAG knowledge base (via CLI or API), a
different pipeline handles parsing, chunking, and embedding.

### Ingestion Flow

```
1. Input       File path (CLI) or uploaded file (API)
                |
2. Parse       DocumentProcessor selects parser by file type
                |
3. Chunk       Text split into segments (configurable size/overlap/strategy)
                |
4. Embed       Chunks embedded via configured provider
                |
5. Store       Vectors written to vector database
                |
6. Track       RAGDocument record created in SQL (status tracking)
```

Over the API the order is the other way round: the `RAGDocument` row is written
first and steps 2–5 run in a background task against a session of their own,
which is why an upload answers `{"status": "processing"}` rather than waiting.
There are two addresses an upload can arrive at — `POST /rag/collections/{name}/ingest`
and `POST /kb/{kb_id}/documents` — and both answer **202** with the same
`RAGIngestResponse`, every field of it, `"document_id": null` included: the vector
store's id for the document does not exist until the worker has indexed it. One of
the two used to omit the key rather than send it null, so a client normalising the
answer got a different shape from each
([#560](https://github.com/vstorm-co/agenticos/issues/560)).
That task is started **after the request's transaction commits** — it is handed
over with `spawn_after_commit`, not `spawn`, and started by the session itself
once the row is durable. Dispatched any earlier it would look for the document
by id, find nothing, and stop, leaving the upload it had already acknowledged in
`processing` forever ([#417](https://github.com/vstorm-co/agenticos/issues/417)).
The same applies to a sync: the `SyncLog` row exists before its flow does. See
[Dispatching background work from a request](architecture.md#dispatching-background-work-from-a-request).

**Each flow builds its own vector store, and closes it.** The store owns a
pooled SQLAlchemy engine, so one built per uploaded document and left behind
keeps its connections until the worker process exits: two hundred uploads used to
mean two hundred abandoned pools, and somewhere short of a hundred documents the
worker reached the database's `max_connections` and every query after that failed
— including the one that would have marked the document failed, so the upload sat
at `processing` with the reason only in a log
([#948](https://github.com/vstorm-co/agenticos/issues/948)). Pooling *within* one
flow is worth having, because a document's chunks are written over that
connection; across flows it is not shared, for the same cross-event-loop reason
`get_worker_db_context` creates a `NullPool` engine per call. **If ingestion
starts failing part-way through a large batch with a connection error, this is
the shape to look for.**

### Supported Formats

`.txt`, `.md` and `.docx` are read by the built-in Python parsers whatever the
collection's parser is. Beyond those, the set follows the parser:

| Parser | Also reads | Needs |
|--------|-----------|-------|
| PyMuPDF | `.pdf` | nothing |
| LiteParse | `.pdf`; images (`.png`, `.jpg`, `.tiff`, `.svg`, …); office formats (`.xlsx`, `.pptx`, `.odt`, `.csv`, `.rtf`, …) | LibreOffice **for office formats only** — images are converted natively |
| LlamaParse | `.pdf`, `.pptx`, `.xlsx`, `.csv`, `.rtf`, `.epub`, `.html`, images | `LLAMAPARSE_API_KEY` |

The backend Dockerfile installs LibreOffice and Tesseract, so office formats and
OCR work out of the box in a container. Running the backend outside Docker, an
office upload to a LiteParse collection is refused with a message naming
LibreOffice rather than failing during conversion.

`GET /api/v1/rag/supported-formats?parser=liteparse` answers for one parser.
These sets are what `DocumentProcessor` can actually route — pinned by
`backend/tests/test_supported_formats.py`, because they used to be aspirational:
a `.xlsx` was accepted, stored, given a document row and dispatched, and then
died in a worker as "Unsupported file type".

### Parser Selection (RAG)

Per collection, on `/rag`, and overridable per upload — not an environment
variable. Stored on `knowledge_bases.ingestion_config`.

| Parser | Best For |
|--------|----------|
| PyMuPDF (default) | Fast local processing, text-heavy documents; the only one that extracts embedded images for description |
| LiteParse | Local, no key, layout-aware; reads office formats and images; markdown output |
| LlamaParse | Complex layouts and scanned PDFs; cloud, billed per page |

### LiteParse options

| Setting | Default | Notes |
|---------|---------|-------|
| `liteparse_output_format` | `markdown` | Reconstructs headings, tables and lists — what the `markdown` chunking strategy splits on. `text` keeps the spatial grid. |
| `auto_ocr` | `true` | Runs LiteParse's cheap text-layer check per document and OCRs only what needs it. OCR dominates the cost of a parse. |
| `ocr_language` | `eng` | Tesseract codes — three letters, `+`-joined for several (`eng+pol`). A language with no pack installed reads nothing; add `tesseract-ocr-<lang>` to the Dockerfile. |
| `liteparse_dpi` | `150` | Higher reads faint scans, slower. |
| `max_pages` | `1000` | The setting that bounds the cost of one document; `parse_timeout_seconds` only bounds the wait. |

### Chunking Configuration

Per collection, alongside the parser:

| Setting | Default | Description |
|---------|---------|-------------|
| `chunk_size` | `512` | Maximum characters per chunk |
| `chunk_overlap` | `50` | Characters of overlap; must be smaller than `chunk_size` |
| `chunking_strategy` | `recursive` | Strategy: `recursive`, `markdown`, `fixed` |

**Strategy comparison:**

| Strategy | Best For |
|----------|----------|
| `recursive` | General text; splits on paragraph, then line, then word, then character |
| `markdown` | Markdown/structured docs; splits at heading boundaries, then by size within each section |
| `fixed` | Uniform chunk sizes; splits on line ends only, so a long line is emitted whole |

All three come from `app/services/rag/_splitters.py`, which replaced
`langchain-text-splitters` in [#158](https://github.com/vstorm-co/agenticos/issues/158)
— the eight packages behind it included `langsmith`, a second hosted-telemetry
SDK in a platform that standardised on Logfire.

Three things about them are worth knowing before tuning the numbers:

- **`chunk_overlap` is a ceiling, not a guarantee.** A chunk repeats as much of
  the one before it as still fits under `chunk_size`, which is frequently less
  than the setting and sometimes nothing at all.
- **A piece with no separator left is emitted whole, not cut.** `fixed` splits
  on line ends only, so a 4 KB line becomes a 4 KB chunk; the splitter logs a
  warning rather than handing the embedding model something it will reject. The
  warning means *over* `chunk_size` — a line of exactly `chunk_size` characters
  is within the limit and passes silently.
- **`markdown` keeps the heading in the chunk**, and until #158 it applied
  neither `chunk_size` nor `chunk_overlap` — a 50 KB section between two `##`
  was one chunk. It now runs the recursive splitter over each section, so both
  settings mean on this strategy what they mean on the others.

Chunk boundaries are what a search matches against, so a collection ingested
before that change keeps the chunks it was ingested with. Re-upload a document,
or re-run `uv run agenticos cmd rag-ingest`, to re-chunk it.

**How many chunks a document has decides how long storing it takes, but no longer
how many round trips.** `insert_document` writes them 200 rows to a statement
(`executemany`, which asyncpg pipelines), where it used to issue one `INSERT` per
chunk in a Python loop inside one open transaction — so a 200-page PDF at the
default `chunk_size` was one to three thousand sequential round trips, five to
fifteen seconds against a managed Postgres at 3-5ms before a single embedding was
paid for ([#950](https://github.com/vstorm-co/agenticos/issues/950)). It is
batched rather than one statement for the whole document because the parameter
list is held in memory and each row carries its embedding rendered as text: at
3072 dimensions that is tens of kilobytes a row.

**An override is checked against the merged pair, not against its own value.** A
per-upload `ingestion` field carries only what it changes, so `chunk_overlap:
4096` sent to a collection chunking at 512 is two individually legal numbers and
one configuration that repeats almost everything it advances past. The merge
re-validates, and the upload is refused with a **400** naming both settings in
`details.fields` — before the file is stored and before a document row exists,
so there is nothing to retry or clean up. It answered 500 with an empty
`details` until [#874](https://github.com/vstorm-co/agenticos/issues/874): the
merge raised a raw Pydantic error, which reaches no handler. The same pair sent
as a collection's own configuration was always refused with a 422, because there
it is a field of a JSON body and FastAPI validates it before the route is
entered.

Both refusals name the same fields, `ingestion_config` for the pair rule and
`ingestion_config.chunk_size` for a setting of its own — so the form marks one
place whichever entry point refused. (The pair rule names the object because
Pydantic attributes a `model_validator(mode="after")` to neither of the two
fields it is about.) The 400 named its fields under `details.errors` until
[#882](https://github.com/vstorm-co/agenticos/issues/882), in Pydantic's own
error format, which nothing on the frontend read: the sentence reached a toast
and no input was ever highlighted.

### Embeddings — the model, and whose key pays

Embeddings go out through OpenRouter to an OpenAI embedding model. Both halves
of that call are decided **per collection**, not per deployment, by
`app/services/embedding_resolution.py`:

| | |
|---|---|
| **Model and width** | Recorded on the knowledge base at creation (`embedding_model`, `embedding_dim`) and never changed afterwards — `PgVectorStore` writes `embedding vector(N)` once, so a second model either cannot be written or is silently compared against vectors from another space. `EMBEDDING_MODEL` decides only what a *new* collection is built with. |
| **Credential** | The vault key chosen on the collection (`embedding_secret_id`), which is what the organization is billed for. A collection that chose none embeds on the deployment's `OPENROUTER_API_KEY`. |

The key is validated at creation — a key another organization holds, one of the
wrong purpose, or one the chooser cannot themselves see is refused there, where
the person choosing can fix it. That last one is why binding needs
`secrets:view` on the key and not only `collections:edit` on the collection:
binding a key is lending it, since the collection's embeddings bill it for
everyone who can write the collection. The picker only ever offered keys the
chooser can see, but the API takes an id and an id is guessable, so until
[#912](https://github.com/vstorm-co/agenticos/issues/912) a Member could bind
another member's **private** key by supplying its UUID. A key they cannot view is
refused as one the vault does not hold, so the refusal cannot enumerate somebody
else's private secrets.

At embed time nothing is refused: a chosen key that has since been deleted,
cannot be unsealed, or does not hold an API key falls back to the deployment's,
because *whose key pays* must never decide *whether documents can be found*.

That fallback is announced rather than assumed. The resolution carries which of
the five sources it landed on, ingestion writes the degraded ones into the
Prefect run's log, and a deployment with no key of its own fails with a message
naming the collection and which key it tried — not with advice to set a variable
about a collection that already had a key. Before #306 the ingestion worker was
the one caller that never asked the resolver at all, so every uploaded document
was embedded with the deployment's model and key whatever its collection had
chosen.

### Vector Storage
Vectors are stored in **pgvector** using the existing PostgreSQL database.
No additional services needed.

**One table per collection, created at runtime.** The store issues `CREATE TABLE IF
NOT EXISTS rag_<collection>` the first time a collection is written to, so those
tables exist in the database and in nothing else — no model declares them and no
migration creates them, because a deployment holds as many as somebody has made
knowledge bases. Alembic does not own them, and `alembic/env.py` says so through
`include_name`: without that, `make db-check` read every one as a table the models
had dropped and failed on any database that had ever ingested a document. The
predicate lives in `app/db/vector_tables.py`, and it is narrower than the prefix on
purpose — `rag_documents` *is* a model table, and excluding it would have turned the
gate off for the one table ingestion writes through.

The store answers the same question with the same predicate: `list_collections`,
which is what `rag-collections` prints, reports a `rag_` table only when no model
declares it. Matching the prefix alone had it reporting `rag_documents` as a
collection called `documents` — one nobody created, whose "vector count" was the
number of ingested documents, and which any caller could then ask to search.

#### What a collection may be called

A collection name is a string a caller chooses and the store builds identifiers
out of, so **one function decides whether it is usable** —
`validate_collection_name` in `app/db/vector_tables.py`. Four refusals, each a 400:

| Refused | Because |
|---|---|
| Not a bare identifier — `foo-bar`, `2024_reports`, anything with a space or a quote | The store interpolates the name into DDL unquoted. A leading digit only *looks* safe: the `rag_` prefix supplies the letter the name is missing. |
| Any upper case — `Handbook` | Postgres folds an unquoted identifier, so `Handbook` and `handbook` are one table. Nothing above the database can see it: names are compared as whole strings everywhere else, so the two are two rows the platform believes are two collections. Refused rather than lower-cased — storing a name the caller did not type is exactly the reinterpretation this rule exists to avoid. |
| Longer than 45 characters | Postgres keeps 63 bytes of an identifier and truncates the rest silently. `rag_<name>` fits at 59, but `rag_<name>_embedding_idx` does not, and the bound is the longest identifier — not the shortest. |
| `all` | Reserved. |
| A table the models own — `documents` | See below. |

Two of these are the same failure reached differently, and both are worth a
sentence. The length bound is the one that reads as pedantry and is not. Two collections
agreeing up to the truncation point are **one object**: one table if the name was
too long, so either organization's `DROP` destroys the other's vectors and every
search crosses between them; and one index if only the index name was, which is
quieter — `CREATE INDEX IF NOT EXISTS` finds the first collection's index already
there and builds nothing, leaving the second unindexed at whatever width the first
was built at. Nothing above the database can see either, because a collection name
is compared as a whole string everywhere else — which is also why case matters: a
spelling is a shorter road to the same shared table, and refusing upper case
closes a second one with it. `_collection_exists` compared `rag_Handbook` against
`information_schema.tables`, which stores the folded name, so it never matched and
`search`, `get_documents` and `get_document_chunks` answered **empty** for any
collection with a capital in it. That path is gone rather than fixed: such a name
is now refused where the table name is built, before anything can ask.

**A collection may not be named after a table the models own**, which is the
runtime-table predicate read a third way — asked of a name before its table exists.
Refused both at the API and in the store itself, because `rag-drop <name>` reaches
the store with no route in between. The name that made this necessary is
`documents`: prefixed, it *is* the tracking table, so dropping such a collection
aimed `DROP TABLE IF EXISTS` at every organization's ingestion history. The refusal
is derived rather than listed, so a `rag_`-prefixed model table added later is
covered, and a collection called `documents_archive` — which a literal exclusion
would have taken with it — is not affected.

**And the name has to be free.** The vector namespace is deployment-global: two
knowledge bases holding one collection name share one table, so a name already held
outside the caller's reach is refused with a 409 —
`CollectionAccessService.claim`, which `POST /kb` and `POST /rag/collections/{name}`
both call. Only one of them used to. `POST /kb` wrote whatever `collection_name` it
was sent, so a member with `collections:edit` could aim a knowledge base at another
organization's vector table and then read and write it through every gate
afterwards, because a collection resolves through whichever knowledge base the
caller *can* read — and now one of them is theirs. A name a caller does not supply
is derived from the display name plus six random hex characters, and is claimed on
the same path rather than trusted for being random.

`documents` was also the **default** collection, so the CLI quickstart used to aim
at the tracking table; the default is now `default`. A knowledge base created with
the old name before this landed still exists and is still deletable, but nothing
can be ingested into it — delete it and create one under another name. Nothing is
lost in doing so: an ingest into that collection has never succeeded, because
building the vector index on a table with no `embedding` column fails.

### Who may reach a collection

Collections are not global, and nobody inside an organization is an "admin" for
this purpose — there are no roles on a route here, only permissions
([permissions](permissions.md)).

A collection has two names. One is the vector table the chunks live in, which is a
string any caller can type into a URL; the other is the `knowledge_bases` row that
owns it, and only that row knows an organization. **The row is the authority**: every
`/rag` and `/kb` route resolves the name through it, in
`app/services/collection_access.py`, before touching a vector, a document or a sync
source. The listing and the per-resource routes read the rule from that one place,
because it was two copies of it — `/rag/collections` filtering by organization while
`/rag/collections/{name}/info` did not — that once let one tenant read another's.

Three scopes on the row, and no fourth:

| Scope | May read | May write |
|---|---|---|
| `personal` | its owner | its owner |
| `org` | `collections:view` reaching the row | `collections:edit` reaching the row |
| `app` | anybody in the deployment | the deployment superadmin (`is_app_admin`) |

"Reaching the row" is `resolve_access`, the same decision every shareable resource
takes: the caller's scope for that permission, widened by any explicit grant on that
one collection. A grant widens what a role allows and never narrows it, so **a Viewer
holding an explicit `edit` grant can manage that collection** — the case a role gate
would refuse before ever looking. That is why the per-resource routes carry no
`require(...)` and hand the decision to the service instead.

What that buys, per operation:

| | |
|---|---|
| Search — `POST /rag/search`, and the agent's retrieval tool | `collections:view`. Every collection named is resolved before the first vector is read, and one the caller cannot reach refuses the **whole** search rather than being quietly dropped from it |
| Read — listing collections and documents, collection stats, a document's parsed text or original file, sync and ingestion logs | `collections:view`, and each answer holds only the collections that caller can reach |
| Write — creating and dropping a collection, uploading, ingesting, retrying, deleting a document, configuring or cancelling a sync source | `collections:edit` |
| `POST /rag/sync/local` | The one exception, and it keeps `is_app_admin`: its `path` names a directory on the **server** rather than anything a tenant owns, so opening it to `collections:edit` would hand every member a read of arbitrary server files, ingested into a collection they can then search |

A refusal is reported as **"Collection not found"**, with the same message and details
an absent collection produces. Anything else turns the API into an oracle: these names
are derived from what people call their knowledge bases, so confirming that
`acme_handbook_d1fac1` exists somewhere is already information.

**Within a collection there is no per-document isolation.** Access is decided at the
collection, so reaching one reaches every document in it — which is the thing to weigh
when deciding what to ingest where.

### Document Tracking


Ingested documents are tracked in the SQL database via the `RAGDocument` model:

| Field | Description |
|-------|-------------|
| `collection_name` | Target collection |
| `filename` | Original filename |
| `filesize` | File size in bytes |
| `filetype` | File extension (without dot) |
| `status` | `processing`, `done`, or `error` — the `DocumentStatus` members, and the only three values the column holds. A collection's *indexed* count filters on `done`; it filtered on a fourth value nothing has ever written until [#148](https://github.com/vstorm-co/agenticos/issues/148), so every knowledge base reported `indexed_count: 0` however many documents had finished |
| `error_message` | What failed, if `status` is `error` — see below |
| `vector_document_id` | ID in the vector store |
| `chunk_count` | Number of chunks created. Recorded since [#147](https://github.com/vstorm-co/agenticos/issues/147); a document ingested before it holds `0` and its collection's card under-reports until it is re-ingested |
| `storage_path` | Path to original file (for re-ingestion/download) |
| `created_at` | Ingestion start time |
| `completed_at` | Ingestion completion time |

**A replacement retires the row it replaced.** Every ingest path — the upload,
the CLI, a sync run — writes a *new* tracking row, while an ingest with
`replace=true` deletes the vector document it supersedes and inserts one. So the
older row is left describing vectors nobody holds: its `chunk_count` keeps being
summed into the collection's totals, and its parsed-content view has nothing to
read. Completing an ingest therefore deletes the tracking rows pointing at the
vector document it replaced, along with their stored copies of the file. Without
that a directory synced nightly reported a collection growing by its own size
every night.

Failed ingestions can be retried via `POST /rag/documents/{id}/retry`. It
re-reads `storage_path` — the copy the upload kept for exactly this — and
dispatches the parse again, replacing whatever the failed attempt indexed. A
document that did not fail, or that predates uploads keeping their file, is
refused with a 400 rather than moved to `processing`
([#441](https://github.com/vstorm-co/agenticos/issues/441)).

### What a failed ingest says

`error_message` is a stored column, rendered on the documents page and in a
source's sync history to everyone who can see the collection. So it carries a
summary rather than whatever the client that failed happened to say:

```
The document could not be indexed (AuthenticationError) - check the
collection's embedding credential, then retry the upload. The worker log has
the full error.
```

Three parts, and each is there for a reason. **The stage** — parsing, indexing,
recording the outcome, or a whole sync — is the one thing the reader cannot
work out afterwards, and it separates a file this collection's parser does not
read from a credential the provider refused. **The exception's type** is kept
because a class name is a symbol: it says the credential was refused or the
upstream timed out without naming the host that said so. **The advice** is what
the reader can actually do.

One failure is reported by up to three handlers — the stage that raised, the
check that a returned failure is not `done`, and the flow's backstop — and the
**first** one to record it keeps the row, because it is the innermost and the
most specific. A retry clears the message, so the next attempt records its own.

A refusal this platform raised itself is passed through whole instead, because
its message is written here and is the most useful thing to show: *"No embedding
credential is configured for this collection"*, *"Organization monthly budget
exhausted: $40.15 spent of $40.00 limit"*.

What is **not** stored is the failing client's own text. A provider SDK, `httpx`,
`boto3` and the Google Drive client all put the request they were making into
their exception message, which routinely means an endpoint, an internal host, a
bucket, or a URL with a key in its query string — and unlike an HTTP error body,
a column is read again weeks later by anyone who opens the failed document. That
text is not lost: every one of these call sites logs it with `logger.exception`,
so the worker log has the message and the traceback, and a Prefect flow that
re-raises has both in its run. `app/services/rag/failures.py` is where the two
are separated.

The log is a smaller audience than the column, not a safe one — treat a worker
log as something only operators read, and see [#440] for why the redaction
filter this deployment ships does not currently scrub it.

[#440]: https://github.com/vstorm-co/agenticos/issues/440


### Sync Operations

Sync operations are tracked via the `SyncLog` model, recording source, mode,
total files, ingested/updated/skipped/failed counts, and timing. View sync
history via `GET /rag/sync/logs`.

**Which stored document a file corresponds to is one question, asked once.**
`IngestionService.existing_document` reads the collection's document listing a
single time and answers with both the document's id and its stored
`content_hash`, in one precedence: a `source_path` match beats a `filename`
match, and a `content_hash` match is the last resort. The two answers come back
together on purpose — they are facts about *one* document, and while they were
computed by separate lookups they could disagree, so a sync compared a live
file's hash against a different document's and either re-embedded an unchanged
file every night or skipped a changed one as current
([#548](https://github.com/vstorm-co/agenticos/issues/548)). That also made
ingesting one changed file read the whole collection up to four times; it is now
once for the decision and once inside the ingest
([#566](https://github.com/vstorm-co/agenticos/issues/566)). Reading it at all is
still a full scan — [#27](https://github.com/vstorm-co/agenticos/issues/27) is the
pagination that would fix that.

`new_only` skips a file whose stored hash matches, `update_only` skips one that
is unchanged and ignores one that is new, and `full` replaces whatever it
matches. A store that cannot answer the listing is treated as "no match" rather
than as a match: a failed query is not evidence that a document is absent, but
acting on it as though a document *were* present would delete one.

**That is the local-directory sync. A connector sync implements none of it**
([#990](https://github.com/vstorm-co/agenticos/issues/990)): `sync_source_flow`
downloads and ingests every file the connector lists, `sync_mode` reaches only
`ingest_file`'s `replace` argument, and `ingest_file` never skips — so on the
default `new_only` the previous document is neither found nor deleted and a
duplicate is inserted on every run. The `skipped` counter beside it is
initialised and never incremented, which is what a sync log truthfully reporting
`skipped=0` every night has been saying all along.

One source's own history is `GET /kb/{kb_id}/sync-sources/{source_id}/logs`. The
source is resolved against that knowledge base first, so a source belonging to
another base answers **404** rather than an empty list — the two render the same
screen otherwise, and one of them is a request that should have failed. Its runs
are then read by source id, which is what keeps `limit` and `total` describing the
same set of rows: a source repointed at another base keeps its earlier runs under
the collection name it had then, and those used to be dropped from the page after
`limit` had already cut it.

### What a sync source is not allowed to decide

A source's contents are not the deployment's to trust, and on a Drive folder
shared outside the organization they are not even the tenant's: sharing is what
folder sharing is *for*, so whoever can drop a file in one chooses the string
the next sync handles. Two of those strings used to be taken at face value, and
`app/services/rag/remote_names.py` is where both are now refused.

**A file name is a label, not a path component.** `../../../../home/app/.ssh/authorized_keys`
is a legal Drive file name, and the connector wrote `dest_dir / file.name`
verbatim — outside the temporary directory the worker had made, wherever its uid
could write, and then ingested from there. The name is now reduced to its final
component and the result *resolved and confirmed* to be a child of the sync
directory, so `..`, its encodings, its lookalikes and a symlink already sitting
in the directory are one question rather than a list of spellings to keep up
with. A name that is no component at all — `..`, `.`, `/` — is refused; anything
else lands inside as one file. **The destination is `BaseSyncConnector`'s
answer, not a connector's**: an implementation is handed a path and writes to it
(`_fetch`), which is what makes a connector added later inherit the refusal
rather than have to remember it.

**A folder id reaches a query language.** The Drive query wraps a parent id in
single quotes, so `x' in parents or name contains 'salary` is a well-formed,
wider query. A folder id is now checked against what Google can issue — letters,
digits, `-` and `_` — where the query is built, which is the one funnel both the
configured folder and every sub-folder id pass through. `validate_config`
asks the same question, so a hostile value is answered by the route that
accepted it rather than by a sync log an hour later.

**A Google Drive source runs on its own credential or not at all.** The
connector used to fall back to `GOOGLE_DRIVE_CREDENTIALS_FILE` whenever
`service_account_json` was absent, which meant a tenant's folder id chose what
was listed under the *operator's* service account and whatever that account had
been shared. The fallback is gone; the setting now serves only the
`rag-sync-gdrive` CLI command, which an operator runs from their own shell.

### The credential is a vault secret, not a config field

`sync_sources.config` says how to *find* the documents — a folder id, a bucket, a
prefix — and holds nothing that has to be kept. What authenticates is a vault
secret the source names in `secret_id`: a `gcp_service_account` for Drive, an
`aws_credentials` pair for S3, declared by the connector as `SECRET_KIND` and
offered to the wizard as `secret_kind` on the connector listing.

It used to be in `config`, encrypted by `app/core/crypto.py` — one
deployment-wide Fernet key over every tenant's credential, which is the weakness
the vault exists to remove, and the one place `CLAUDE.md`'s "there is no second
mechanism" was untrue. That module is gone
([#937](https://github.com/vstorm-co/agenticos/issues/937)). Three things follow:

- **A credential is added once and referenced.** Five knowledge bases fed from one
  Drive folder used to mean the same JSON pasted five times, rotated five times and
  revoked in five places. Cloning an integration now copies the reference.
- **The wizard offers what the organization holds**, filtered to the kind the
  connector needs, and links to the Vault when there is none — `InlineSecret` is
  not used here because it handles `api_key` only, and a service account is a
  multi-field form whose honest place is the Vault.
- **The service refuses a config carrying a credential.** Posting the old field
  names is answered with "a credential does not go in a source's configuration",
  rather than being dropped so the source stores and then cannot authenticate.

Reading it happens where there is a session and a tenant: the worker unseals the
secret for the source's own organization and hands it to the connector beside the
config. A connector cannot reach the vault itself, and a source whose secret was
deleted syncs no further — the connectors have no deployment-wide fallback and
must not grow one.

### Who ends up able to read what a source ingested

**The collection is the permission boundary, and a source's reach is its
credential's permissions narrowed by its own configuration.** A sync source
ingests into exactly one collection, access is decided at the collection (see
[Who may reach a collection](#who-may-reach-a-collection)), and there is no
per-document isolation inside one — so **everything that source reads becomes
readable by everyone who can read that collection.**

The two halves of that reach are not equally reliable, which is the part worth
knowing. A Drive source is bounded by its `folder_id` and an S3 source by its
`bucket` and `prefix`, so a broad credential pointed at one folder ingests one
folder. But `config` is a field on the row, editable by anyone holding
`collections:edit` on that collection — so **configuration narrows the reach and
cannot be relied on to keep it narrow**, while the credential's own permissions
are a ceiling nothing in this product can raise. A Confluence token good for the
whole instance, on a source somebody later repoints at a wider space, publishes
the whole instance to every member holding `collections:view`; the same token
scoped to one space cannot, whatever the config says.

That is a decision somebody has to make, and the platform's answer is to make it
**explicit rather than clever**. The alternative — mirroring each source's own
ACLs into the store and filtering at retrieval — is not on the roadmap, and the
reasons are worth stating so it is not proposed again as an obvious win:

- **There is no identity map.** A SharePoint ACL names Entra principals, a
  Confluence one names Atlassian accounts, and neither is an `organization_members`
  row. Guessing the correspondence by email address is how a platform grants the
  wrong person access to the right document.
- **An ACL is a moving target.** A permission changed in the source is invisible
  here until the next sync, so a mirrored ACL is *stale authorization* — worse
  than none, because it looks like an answer.
- **A crawler has no ACL at all**, and a git repository's is the hosting
  platform's rather than the document's. A model that only works for two of the
  candidate connectors is not the model.

So the rule for whoever creates a source, and the thing a wizard step has to
say: **scope the credential, not just the config.** A service account shared into
one folder, an Entra app consented to one site rather than a tenant, a
Confluence token limited to a space — that is the half of the reach an edit to
the source cannot widen. Pointing a broad credential at a `personal` collection
narrows the readers but not what was ingested; a narrow credential on an `org`
collection is the shape to aim for.

Two things this rule owes and does not yet have, each filed:
[#982](https://github.com/vstorm-co/agenticos/issues/982) states the consequence
in the wizard where the collection is chosen, and re-asks when a source is
repointed at a different one; [#983](https://github.com/vstorm-co/agenticos/issues/983)
records creating and repointing a source in the audit log, which is what gives
"who decided this collection gets that credential's reach" an answer after the
fact. Today both are silent, which is exactly the implicitness this section
exists to name.

### What a new connector owes

A connector is `list_files` + `_fetch` + a `CONFIG_SCHEMA`, and the API calls are
the cheap part. Three things are not, and a connector without them is a bill or a
surprise rather than a feature:

- **A change signal** — and, today, the sync path that would use it.
  `sync_source_flow` lists, downloads and ingests every file unconditionally:
  `sync_mode` reaches one argument and `ingest_file` never skips, so a scheduled
  source re-embeds everything nightly and, on the default `new_only`, inserts a
  *second copy* each run
  ([#990](https://github.com/vstorm-co/agenticos/issues/990)). Naming a signal
  therefore buys nothing on its own, which is why #990 comes before the
  connectors are worth having: it is the comparison step, and the local-directory
  flow already has one to copy. Name the signal in the connector's docstring
  anyway — a Graph `delta` token, a page's `version.number`, a commit sha, an
  HTTP `ETag` — because which one a connector can offer is what decides whether
  that comparison happens before the download or after it, and fall back to
  `content_hash` only where the remote system genuinely offers none.
- **A credential scoped at the source.** See the section above. A connector's
  `SECRET_KIND` says what shape the credential is; nothing in the platform can
  say how wide it was issued, which is why the guidance belongs where the source
  is created.
- **A file count somebody has thought about.** Reading a collection's document
  listing is still a full scan
  ([#27](https://github.com/vstorm-co/agenticos/issues/27)), so a connector that
  brings thousands of files makes that pagination urgent rather than tidy.

**A sync connector is not an MCP server.** MCP is how an agent reaches a product
*live*, mid-run; a sync source is a scheduled bulk pull with change detection
whose output is chunks in pgvector. Notion-as-a-tool is an MCP server;
Notion-as-a-corpus is a connector. Several candidates are honestly both, and the
question to answer before writing one is which half is being built — see
[mcp](mcp.md).

Which connectors are being built, and in what order, is decided in
[#938](https://github.com/vstorm-co/agenticos/issues/938): a web crawler
([#984](https://github.com/vstorm-co/agenticos/issues/984)), SharePoint and
OneDrive ([#985](https://github.com/vstorm-co/agenticos/issues/985)), Confluence
([#986](https://github.com/vstorm-co/agenticos/issues/986)), a git repository's
documentation ([#987](https://github.com/vstorm-co/agenticos/issues/987)), and
then Azure Blob and GCS once `S3Connector` is an object store rather than an S3
one ([#988](https://github.com/vstorm-co/agenticos/issues/988)). Notion, Slack
and email archives are decided **against** for now, each for a reason recorded
there — the last two because a conversation retrieves badly and the channel
integrations already put an agent *in* Slack.

### A connector's refusal names the field it is about

`validate_config` answers a `ConfigRefusal` — a sentence, and the field that
sentence is about — or `None` when the config is acceptable. The connector names
its own `CONFIG_SCHEMA` key; `SyncSourceService` roots that against the document
the wizard posted (`folder_id` → `config.folder_id`) and raises it with
`refused_field`, so it reaches the browser as `details["fields"]` in the one
shape a form reads (`app/core/field_errors.py`) and the configure step marks the
input the connector rejected.

It used to answer `(bool, str | None)`, and a flag with a sentence cannot say
*which of four inputs* was wrong. The folder-id check above knew, the reader
did not: the wizard showed one line of prose under four boxes.

Naming a field is optional, and deliberately so. A connector may refuse a config
without blaming one part of it — connectivity that fails, two credentials that
do not belong to the same account — and `ConfigRefusal(message=...)` with no
field is the honest answer there. Inventing a field name would send somebody to
edit a value that was accepted. `checked_drive_folder_id` names none for the same
reason: it answers three sinks and only one of them was sent a form to mark.

### Image Description

When processing documents that contain images, the system can optionally
describe images using LLM vision capabilities. Image description is a
per-collection setting: turn it on in the knowledge base's ingestion
configuration and pick a vision-capable model profile there. The picker is the
one the agent builder uses, so a provider, a model and its key can be defined
without leaving the dialog — a deployment with no model profiles yet is not a
dead end. What it does not offer is deleting a profile: that belongs where an
organization's models are managed, because every agent pointed at one loses it.
The generated descriptions are included in the document text for better semantic
search.

## From a channel

A file sent to a Slack, Telegram or Mattermost bot enters here, not beside here.
The adapter fetches it with the bot's own credential, it goes through the same
validation a browser upload does, and it becomes the same `ChatFile` row — so the
routing above applies unchanged and a channel cannot become the lenient path.

What differs is only what a refusal looks like: there is no form to show an error
in, so a file that was too large or of an unsupported type is named in the bot's
reply. See [Channels](channels.md#files).
