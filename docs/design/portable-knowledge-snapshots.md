# Portable knowledge snapshots

Knowledge export has three independent choices: the definition, stored originals,
and parsed text. Vector indexes are not portable. `kb_index` is absent from export
options and refused on import, including manifests claiming it without an asset.

The definition carries the embedding model/provider/dimension and parser/chunker
configuration. Vault keys, image model profiles and local embedding/OCR services
are schema-declared references. Destination reuse is authorized again. Vault
credentials, source endpoint addresses, connector credentials, source URLs and
physical collection/storage names never enter the definition. Historical document
parser settings retain their settings but clear credential/profile/endpoint IDs;
explicit indexing uses the destination knowledge base's current configuration.

A new knowledge base is private and owned by the importer, with a fresh collection
name. Import neither creates a vector table nor parses, embeds, publishes or
schedules anything. Optional keys/endpoints can be skipped and configured later.
A source's custom OpenRouter embedding URL must be configured at the destination;
it is not silently copied from another deployment.

## Content and bounds

A document descriptor contains a logical document ID, filename, file size/type,
parser settings and optional organizational unit. It never contains its chunks.
Each original and parsed snapshot is a separate content-addressed ZIP asset,
named by document ID and content layer. Equal filenames remain distinct documents.
YAML/JSON can carry an empty knowledge-base definition; files and parsed content
require ZIP.

The existing 4 MiB manifest and 2 GiB expanded ZIP limits remain. A knowledge base holds
at most 1,000 document descriptors; a transfer holds at most 10,000 parsed chunks. A parsed
snapshot is at most 256 MiB, with 1 MiB per JSONL record. Originals are streamed
through file storage; vector chunks are read in stable, 100-row keyset batches
under the exact knowledge-base and tenant scope. Export retains no full chunk
array. Stream cancellation closes readers and temporary directories settle before
cleanup returns.

Imported documents report `stored`, zero indexed chunks and no vector document ID.
`has_file` reflects the original; `has_parsed_content` reflects a parsed snapshot.
The existing parsed-content endpoint reads that snapshot without OCR or a model.
It groups the exact chunks into pages without merging overlap. Explicit retry of
a stored original starts normal ingestion using destination settings; parsed-only
snapshots need an original before indexing. The ingestion upload size limit still
applies before loading an imported original for retry.

## Ownership and failure

Temporary transfer objects live under `portability/<journal UUID>/`. Imported
objects live under `portable-content/<journal UUID>/<resource>/<document>/<layer>`.
Neither uploaded filenames nor source paths choose an object key. Even identical
content receives independent persistent document ownership, so deleting one copy
cannot break another document.

The transfer journal is committed before work starts and survives owner deletion.
Copied files are named deterministically from that journal. Relational imports
and their idempotency receipt commit only after the current worker lease is fenced.
A failed lease or cancellation rolls all rows back. Expiry cleans abandoned files
through the retained journal, including writes from failed attempts; successful
imports keep only the prefixes owned by created knowledge bases. Ordinary document,
knowledge-base and organization teardown includes originals and parsed snapshots
in existing durable cleanup jobs. Retention includes `stored` documents as terminal
rows and deletes both objects.

Migration `0371_portable_document_snapshots.py` adds a nullable snapshot path;
existing rows remain unchanged. Downgrade refuses while any document still owns a
snapshot, because dropping the column would orphan its file. Delete those documents
through the application before downgrading, or restore a backup containing both
database and storage.

## Verification

Focused unit tests cover exact text, corrupt/unknown assets, invalid index claims,
limits, 10,000-chunk boundaries, local/S3 storage contracts and independent duplicate
ownership. The two new content modules have 100% statement and branch coverage.
Real PostgreSQL tests cover cross-organization ZIP copies, private unindexed state,
parsed preview, replay, rollback after lease loss/cancellation, expiry ownership and
205-row vector pagination with foreign tenant/base exclusions. A scratch-schema
migration check verifies upgrade, existing-data preservation, protected downgrade
and downgrade/re-upgrade. No paid providers are used.
