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
3. Classify    Determine file_type: "image", "pdf", "docx", "text"
               |
4. Parse       Extract text content (images skip this step)
               |
5. Store       Save file to media/{user_id}/ via FileStorageService
               |
6. Record      Create ChatFile row in database
               |
7. Link        When message is sent, ChatFile is attached via message_id FK
               |
8. Display     Frontend shows images as thumbnails, documents as badges
```

### Supported File Types

| Category | MIME Types | Extensions | Processing |
|----------|-----------|------------|------------|
| **Images** | image/jpeg, image/png, image/webp, image/gif | .jpg, .png, .webp, .gif | Stored as-is. Sent to LLM as `BinaryContent` for vision analysis. |
| **PDF** | application/pdf | .pdf | Text extracted via configured PDF parser. Appended to prompt as context. |
| **DOCX** | application/vnd.openxmlformats-officedocument.wordprocessingml.document | .docx | Paragraphs extracted via `python-docx`. Appended to prompt as context. |
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
| pdf, docx | parsed text pasted inline | the original **and** a `.txt` beside it; reference |
| image | `BinaryContent` | `BinaryContent` **and** written; reference names the path |

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

- Maximum file size: `MAX_UPLOAD_SIZE_MB` environment variable (default: **50 MB**)
- The limit is enforced server-side after reading the file content.

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
| `file_type` | String | Classified type: `image`, `pdf`, `docx`, `text` |
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
That task is started **after the request's transaction commits** — it is handed
over with `spawn_after_commit`, not `spawn`, and started by the session itself
once the row is durable. Dispatched any earlier it would look for the document
by id, find nothing, and stop, leaving the upload it had already acknowledged in
`processing` forever ([#417](https://github.com/vstorm-co/agenticos/issues/417)).
The same applies to a sync: the `SyncLog` row exists before its flow does. See
[Dispatching background work from a request](architecture.md#dispatching-background-work-from-a-request).

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

Per collection, on `/kb`, and overridable per upload — not an environment
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
| `recursive` | General text; splits by paragraph, then sentence, then word |
| `markdown` | Markdown/structured docs; splits at heading boundaries |
| `fixed` | Uniform chunk sizes; simplest but may split mid-sentence |

### Embeddings — the model, and whose key pays

Embeddings go out through OpenRouter to an OpenAI embedding model. Both halves
of that call are decided **per collection**, not per deployment, by
`app/services/embedding_resolution.py`:

| | |
|---|---|
| **Model and width** | Recorded on the knowledge base at creation (`embedding_model`, `embedding_dim`) and never changed afterwards — `PgVectorStore` writes `embedding vector(N)` once, so a second model either cannot be written or is silently compared against vectors from another space. `EMBEDDING_MODEL` decides only what a *new* collection is built with. |
| **Credential** | The vault key chosen on the collection (`embedding_secret_id`), which is what the organization is billed for. A collection that chose none embeds on the deployment's `OPENROUTER_API_KEY`. |

The key is validated at creation — a key another organization holds, or one of
the wrong purpose, is refused there, where the person choosing can fix it. At
embed time nothing is refused: a chosen key that has since been deleted, cannot
be unsealed, or does not hold an API key falls back to the deployment's, because
*whose key pays* must never decide *whether documents can be found*.

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
| `status` | `processing`, `done`, or `error` |
| `error_message` | What failed, if `status` is `error` — see below |
| `vector_document_id` | ID in the vector store |
| `chunk_count` | Number of chunks created |
| `storage_path` | Path to original file (for re-ingestion/download) |
| `created_at` | Ingestion start time |
| `completed_at` | Ingestion completion time |

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
