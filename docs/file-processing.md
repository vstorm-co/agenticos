# File Processing

This document covers how files are handled in two contexts: chat file uploads
(user-facing) and RAG document ingestion (admin/CLI).

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
- There is no admin override -- admins cannot access other users' chat files
  through the file API.

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
| Longer than 45 characters | Postgres keeps 63 bytes of an identifier and truncates the rest silently. `rag_<name>` fits at 59, but `rag_<name>_embedding_idx` does not, and the bound is the longest identifier — not the shortest. |
| `all` | Reserved. |
| A table the models own — `documents` | See below. |

The length bound is the one that reads as pedantry and is not. Two collections
agreeing up to the truncation point are **one object**: one table if the name was
too long, so either organization's `DROP` destroys the other's vectors and every
search crosses between them; and one index if only the index name was, which is
quieter — `CREATE INDEX IF NOT EXISTS` finds the first collection's index already
there and builds nothing, leaving the second unindexed at whatever width the first
was built at. Nothing above the database can see either, because a collection name
is compared as a whole string everywhere else.

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

### Who reaches a collection

A collection name is a string; the `knowledge_bases` row behind it is the thing
that has an owner, so **the row decides**. Every `/rag` and `/kb` route resolves
the name through `CollectionAccessService`, and a name belonging to another
organization is indistinguishable from one that was never created.

- **Reading** — `collections:view`, and then the row: an `app`-scoped base is
  deployment-wide by design, a `personal` one belongs to its owner, and an `org`
  one takes the caller's scope against the row's owner and visibility, widened by
  an explicit grant. `POST /rag/search` resolves *every* collection it was given
  before reading a vector, and refuses the whole search rather than dropping the
  one it cannot reach.
- **Writing** — `collections:edit` reaching the row, by the same rules. Only a
  platform admin writes to an `app`-scoped base.
- **The one exception** is `POST /rag/sync/local`, which still takes the platform
  admin role: its `path` names a directory on the server rather than anything a
  tenant owns.

This page used to say the opposite — that any authenticated user could search any
collection and that "only admins" could manage them. That was true of a version
where the gate was the platform-admin role, which kept ordinary members out of RAG
entirely while letting any platform admin read every tenant's collections.

### Document Tracking


Ingested documents are tracked in the SQL database via the `RAGDocument` model:

| Field | Description |
|-------|-------------|
| `collection_name` | Target collection |
| `filename` | Original filename |
| `filesize` | File size in bytes |
| `filetype` | File extension (without dot) |
| `status` | `processing`, `done`, or `error` |
| `error_message` | Error details (if status is `error`) |
| `vector_document_id` | ID in the vector store |
| `chunk_count` | Number of chunks created |
| `storage_path` | Path to original file (for re-ingestion/download) |
| `created_at` | Ingestion start time |
| `completed_at` | Ingestion completion time |

Failed ingestions can be retried via `POST /rag/documents/{id}/retry`.


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
