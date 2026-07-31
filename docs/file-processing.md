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

### Embedding Providers
Embeddings are generated using **OpenAI** (`text-embedding-3-small` by default).
Set `EMBEDDING_MODEL` to change the model.

### Vector Storage
Vectors are stored in **pgvector** using the existing PostgreSQL database.
No additional services needed.

### RAG is Global

Collections are shared across **all users**:

- Any authenticated user can search any collection via `POST /rag/search` or
  through the AI agent's RAG tool.
- Only admins can manage collections, upload documents, configure sync sources,
  and view ingestion logs.
- There is no per-user document isolation.

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

### Image Description

When processing documents that contain images, the system can optionally
describe images using LLM vision capabilities. Image description is a
per-collection setting: turn it on in the knowledge base's ingestion
configuration and pick a vision-capable model profile there. The generated
descriptions are included in the document text for better semantic search.
