---
name: rag-knowledge
description: Work with the knowledge base — ingest documents, run semantic search, manage collections, add a sync connector (Google Drive, S3), change a parser or an ingestion setting. Use when populating or debugging retrieval, when a document upload fails or dies silently in a worker, or when "the agent cannot find something that is definitely in the collection". pgvector + per-organization embedding keys.
---

# Knowledge base (pgvector)

**Read `docs/file-processing.md`** for the pipeline and
`docs/howto/add-sync-connector.md` / `docs/howto/configure-sync-sources.md` for
sources. Code: `app/services/rag/` — ingestion, vectorstore, embeddings, connectors.

The model reaches it through the **`knowledge` capability**, whose tool is
`search_documents`. (`search_knowledge_base` is an internal function in
`capabilities/knowledge/_search.py`, not the tool the model sees.) A collection is
searched, never browsed: the model chooses *what* to look for and can never widen
*where* it looks — collections are resolved from the spec before the run.

## CLI

```bash
uv run agenticos cmd rag-ingest ./docs/ --collection docs --recursive
uv run agenticos cmd rag-search "your question" --collection docs
uv run agenticos cmd rag-collections
uv run agenticos cmd rag-stats
uv run agenticos cmd rag-drop <collection> --yes
uv run agenticos cmd rag-sources
uv run agenticos cmd rag-source-add
uv run agenticos cmd rag-source-sync --all
uv run agenticos cmd rag-source-remove <id>
```

Ingestion is parse → chunk → embed → upsert. Heavy ingestion runs as a Prefect flow,
never inline in a request — see the `background-task` skill.

## The four traps

**1. The database must be `pgvector/pgvector:pg16`.** The store issues
`CREATE EXTENSION IF NOT EXISTS vector` on first write; stock Postgres answers
`extension "vector" is not available` — a 500 before any row is committed. If ingestion
500s on a fresh environment, **check the image first**. Every compose file and both CI
jobs pin it; they used to pin `postgres:16-alpine`, which is why no ingestion path had
ever been exercised locally or in CI.

**2. A format list can lie, and the upload is accepted anyway.**
`GET /rag/supported-formats` and the upload validator answer from `PARSER_FORMATS`;
`DocumentProcessor.process_file` is what actually routes. When the two disagree the
upload **succeeds** — file stored, document row committed, task dispatched — and dies
in a worker, so the document sits in the listing with no explanation.
`tests/test_supported_formats.py` pins each parser's set against what the pipeline can
route, **in both directions**. Widening a format set is what that test exists for.

**3. Narrowing an `IngestionConfig` rule breaks existing rows.** It lives in a JSONB
column, so a tighter rule does not only reject new input — it makes stored rows
unreadable, and a Pydantic model refusing one field of one row takes the whole listing
endpoint down with a 500. Adding a field is safe (missing keys take defaults);
narrowing needs a data migration **in the same change**. the OCR language codes are the
worked example. See the `alembic-migration` skill.

**4. A document that parses to nothing.** Silently indexing an empty result is
indistinguishable afterwards from a document that ingested fine and never matches.
Markdown reconstruction returns an **empty fenced block** rather than whitespace for an
unreadable scan, so `.strip()` is not the check.

## Credentials

Embedding keys, connector credentials and a LlamaParse key are organization secrets in
the vault. **`CHANNEL_ENCRYPTION_KEY` is gone** — see the `vault-secrets` skill.
`app/services/embedding_resolution.py` decides which key a collection embeds with, and
it *is* in the gated platform layer.

## Adding a connector

Implement it in `app/services/rag/connectors/` following the Google Drive / S3
connectors, register it so the sync service discovers it, and expose its config fields.
`docs/howto/add-sync-connector.md` is the walkthrough; `docs/patterns.md` has the
registration shape.

## Debugging bad results

1. Is the collection populated? `rag-stats`.
2. Is it bound to *this* agent's spec (`collection_ids`)? An unbound collection is
   invisible, and `knowledge` bound with no collections contributes **nothing at all**.
3. Does the org have `knowledge:read`?
4. Same embedding model throughout? **Do not mix embeddings within a collection** —
   re-ingest if it changed.
5. Did the document actually parse? See trap 4.

## Coverage

`app/services/rag/*` is template-inherited and **outside** the coverage gate — which is
exactly why the invariants above are pinned by explicit named tests rather than left to
a percentage. Three format lists disagreed there for months without anything failing.
