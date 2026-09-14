# FA-039 — RAG metadata filters (issue #1593)

**General design only. The implementation plan is deferred on instruction — this
document stops at the general design + codex critique + resolutions.**

## 1. Problem and current state

FA-039 wants the RAG retrieval path and its agent tool to support metadata
filters: **source, document type, organizational unit, tenant, date and
permissions**. Business filters (source, type, org-unit, date) are chosen by the
caller/model; tenant and permissions must come from trusted server context so a
supplied filter can only *narrow*, never *widen*, access.

What exists today (verified in code):

- **Public filter is a string DSL.** `RAGSearchRequest.filter` is a scalar
  expression string (`app/schemas/rag.py`). Only one clause is ever honored:
  `RetrievalService` regex-extracts `parent_doc_id == "<id>"`
  (`retrieval.py:_parent_doc_id_from_filter`) and passes it to the store as a
  typed `parent_doc_id`. **Every other clause in the string is silently ignored.**
- **The store takes one structured predicate.** `BaseVectorStore.search(...)`
  accepts only `parent_doc_id` (plus `organization_id`), which becomes
  `WHERE parent_doc_id = :doc_id` in `PgVectorStore.search` (`vectorstore.py`).
- **`organization_id` is not a row filter.** In retrieval it scopes only which
  embedding key/model resolves for the collection (`#913`); it is never a WHERE
  conjunct on the chunk rows.
- **Tenant isolation today is at the collection-access layer, not row-level.**
  `CollectionAccessService.readable_all` resolves which `KnowledgeBase` rows (and
  thus `collection_name`s) a caller may reach; the agent tool gets server-resolved
  `kb_collection_names` via `AgentDeps`. **But the physical vector table is
  `rag_<collection_name>`, keyed by name only and _not tenant-unique_** — the
  `knowledge_base.py` service comments state plainly the "vector namespace is not
  tenant-unique, so a name a sibling — or another org — could also use" (#913).
  Two organizations that pick the same collection name share one physical table,
  and nothing in `search()` separates their chunks. This is the latent
  cross-tenant leak FA-039's server-derived **tenant** filter must close.
- **Chunk metadata** (`PgVectorStore._build_chunk_metadata`) holds `page_num`,
  `chunk_num`, `has_images`, `image_count`, and everything in
  `DocumentMetadata.model_dump()` (`filename`, `filesize`, `filetype`,
  `source_path`, `content_hash`, `additional_info`). There is **no**
  `organization_id`, `document_type`, `organizational_unit` or a document date on
  the chunk today.
- **The `_bm25_search` gap.** In hybrid mode `RetrievalService.retrieve` passes
  `parent_doc_id` to the vector `store.search`, but `_bm25_search`
  (`retrieval.py:97`) calls `self.store.search(...)` **without** `parent_doc_id`
  (and without any scope). Its unrestricted candidate rows are then RRF-fused back
  in, reintroducing chunks the vector path had filtered out — including, given the
  shared-table issue, another tenant's chunks. `retrieve_multi` likewise forwards
  no filter/scope.

The model's tool (`search_documents` in `knowledge/_toolset.py` →
`search_knowledge_base`) exposes only `query` and `top_k`; collections and
`organization_id` come from `AgentDeps` server-side. This is the security pattern
we extend, per `deps.py`: *tool parameters are model-controlled and untrusted;
deps are resolved server-side.*

## 2. Design overview

Replace the single-clause string DSL and the single `parent_doc_id` argument with
**two separate structured inputs** that meet only inside the store:

1. **`RetrievalFilters`** — the *business* filters, caller/model-supplied,
   validated, all optional, **narrowing only**.
2. **`RetrievalScope`** — the *server-trusted* restrictions (tenant now;
   per-document authorization slot for FA-037 later), built exclusively from
   `ctx`/`AgentDeps`, never from request or tool parameters.

The retrieval service composes `scope AND filters` and hands the store **one
structured object**. Each `BaseVectorStore` implementation translates that object
into its own backend query (pgvector → parameterized SQL WHERE; future OpenSearch
→ bool query). The service builds no SQL and speaks no DSL.

### 2.1 The business filter contract (`RetrievalFilters`)

A Pydantic model (in `app/schemas/rag.py` or a dedicated `rag_filters` module),
all fields optional:

| Field | Type | Meaning | Multi-value |
|---|---|---|---|
| `source` | `list[str] \| None` | ingestion origin (e.g. `upload`, `s3`, `gdrive`) | OR within field |
| `document_type` | `list[str] \| None` | document type (mime/filetype or semantic type) | OR within field |
| `organizational_unit` | `list[str] \| None` | department/team tag | OR within field |
| `date_from` | `date \| None` | inclusive lower bound on the document date | — |
| `date_to` | `date \| None` | inclusive upper bound on the document date | — |
| `parent_doc_id` | `VectorDocumentId \| None` | restrict to one document (the existing capability, now typed) | — |

**ID namespace (codex-2 R6).** `parent_doc_id` is the **vector document id** — the
parser-created `Document.id` stamped on every chunk (`services/rag/models.py`),
which the relational tracking row records separately as
`RAGDocument.vector_document_id` (a `String(255)`, *not* the `RAGDocument` primary
key UUID). Filters and the scope's `authorized_document_ids` both carry vector
document ids; a trusted relational id (the `RAGDocument.id` UUID) must be
**translated to its `vector_document_id`** before it reaches the store, or the
predicate matches nothing. This is stated so an implementer cannot compare the two
namespaces by accident, and so permission intersection (2.7) and the backfill (2.5)
join on the same key. A typed `VectorDocumentId` (a thin `str` newtype) is
preferred over a bare `str` so the distinction is visible in signatures.

Semantics: **within a field, multiple values are OR; across fields, AND.**
**Tri-state, explicit (codex-2 R1):** for a business filter dimension, `None` (the
field is absent) imposes no restriction; a **non-empty** list is an allow-list; an
**empty list is rejected at validation** (a supplied-but-empty filter is a caller
error, never silently "match everything"). This closes the fail-open ambiguity
where `[]` read as "unrestricted". The authorization dimension is the opposite
default and lives only in `RetrievalScope` (2.2): there `None` = "no per-document
narrowing applied", but an **empty authorized set means match nothing**
(empty-denies-all), so a resolver that returns "no documents" can never read as
"all documents". Validation: `date_from <= date_to`; where a closed vocabulary
exists (e.g. `document_type` against known mime/types) reject unknown values with a
field error via `app/core/field_errors.py`. `RetrievalFilters` sets
`extra="forbid"` (the repo `BaseSchema` does **not**, codex-2 R9) so a caller that
smuggles `organization_id` or any non-whitelisted key is **rejected**, not silently
ignored — making the trust boundary testable rather than only structural. The model
contains **no tenant field and no authorization field** — those dimensions are
structurally *inexpressible* here, so a caller cannot even name them (see 2.2).

Whitelisting for the tool: the agent tool exposes only the whitelisted business
dimensions (`source`, `document_type`, `organizational_unit`, `date_from`,
`date_to`). `parent_doc_id` is not offered to the model (the model chooses *what*,
not *which stored id*); the API keeps it for programmatic callers. Every exposed
argument is optional and typed on the tool signature so PydanticAI validates it.

**Filter-value discoverability (self-review M3).** `document_type` is validated
against a closed vocabulary, but `source` and `organizational_unit` are otherwise
free-form. Combined with fail-closed missing-field behavior (§2.4), a caller — and
especially the model driving the agent tool — that guesses a value the corpus does
not use (`organizational_unit="Legal"` when the stored value is `"legal-dept"`) gets
**silently empty results, not an error**. The contract must therefore make the valid
values discoverable rather than guessable: a lightweight facet endpoint / tool
affordance that returns the distinct `source` and `organizational_unit` values in
scope (tenant- and collection-scoped like every other read), and — for the agent
tool — surfacing those values in the tool description or as an enum where the set is
small and stable. Without this, the filters are technically correct but practically
unusable by the model. Covered by a named test (a filter value not present in the
corpus returns empty *and* the facet list omits it).

### 2.2 The server-trusted scope (`RetrievalScope`)

A separate structure built **only** from trusted context:

| Field | Source | Purpose |
|---|---|---|
| `organization_id` | `ctx.organization_id` (API) / `AgentDeps.organization_id` (tool) | the **tenant** conjunct — the security-bearing restriction |
| `authorized_document_ids` / auth predicate | server-derived (FA-037 slot) | per-document authorization. **`None` = slot not populated → no per-document narrowing (FA-039 default).** A **populated but empty** set means match nothing (empty-denies-all, codex-2 R1) — it is never conflated with `None` |

The scope is constructed at the trust boundary:

- **API route** (`rag.py:search_documents`): from `ctx: Auth`, after
  `access.readable_all(ctx, names)` has already resolved collection access. The
  request body carries only `RetrievalFilters`.
- **Agent tool** (`knowledge/_toolset.py` → `_search.py`): from `ctx.deps`
  (`organization_id`, and later the authorized doc set). Tool parameters carry
  only business filters.

**Why widening is structurally impossible:**

1. Business filters and scope are *different types built in different places*.
   There is no field on `RetrievalFilters` that can express tenant or
   authorization, so a caller/model cannot supply them at all.
2. `RetrievalScope` is populated from `ctx`/`AgentDeps` only — the same trusted
   channel that already carries `organization_id` and `kb_collection_names`.
3. The store ANDs scope conjuncts into **every** query unconditionally; business
   filters can only add further conjuncts. A conjunction can only *shrink* a result
   set, never grow it. So a supplied filter can only narrow.

Any security-bearing dimension only ever lives in `RetrievalScope`, and the two
never merge into a caller-influenced structure.

**A `None` scope is an error, not "everything" (codex C1).** Tenant-scoped
retrieval (API route + agent tool) requires a non-null `RetrievalScope` with a
non-null `organization_id`; there is no default and no fallback to an unscoped
search. The store treats a missing scope as a programming error and refuses.
Cross-tenant maintenance (the `rag-search` CLI / app-admin) is the single,
separately named path allowed to pass an explicit "unscoped" marker, and a test
asserts no ordinary API/tool caller can reach it.

### 2.3 Enforcement — in the store, on both paths, before top-k

The restrictions are applied **in the backend query (SQL WHERE), not as a Python
post-filter**, so that `LIMIT`/top-k is computed over already-restricted rows.
Post-filtering after top-k would let an unrestricted top-k return few or zero
in-scope rows while in-scope rows exist deeper in the ranking. The same reasoning
is what the OpenSearch adapter will need (filter clause inside the query).

**Filtered ANN recall — moving the filter into `WHERE` is necessary but not
sufficient (self-review H1).** The store is not an exact scan: it builds a
**pgvector HNSW** index and search is `... WHERE <conjuncts> ORDER BY embedding
<=> :q LIMIT :k` (`vectorstore.py`, the `USING hnsw` index + the `ORDER BY
<distance> LIMIT` query). Under HNSW, `WHERE ... ORDER BY <distance> LIMIT k` is a
**filtered ANN scan**: Postgres walks the graph within an `hnsw.ef_search` budget
(default 40) and applies the conjuncts to the nodes it visits. So a *selective*
filter can return **fewer than k — or zero — in-scope rows even when more matching
rows exist deeper in the graph**, which is the very failure mode this section
attributes to Python post-filtering. Crucially the tenant conjunct is now
**mandatory on every query** and, on a shared physical table where one org is a
fraction of the rows, is exactly such a selective filter — so this is a
common-path recall risk, not an edge case. The design therefore commits the store
layer to one of these, made explicit rather than assumed:

- enable pgvector **iterative index scan** (`hnsw.iterative_scan`, pgvector ≥ 0.8,
  off by default) so the scan keeps expanding until it has `k` rows that pass the
  filter, with a bounded `hnsw.max_scan_tuples` ceiling; and/or
- raise `hnsw.ef_search` for filtered queries (a recall/latency trade-off), set per
  statement so unfiltered paths are unaffected; and/or
- for the security-bearing tenant conjunct specifically, prefer **partitioning or a
  per-tenant partial index** over relying on a post-hoc filter of a global graph, so
  tenant selectivity does not degrade recall.

Whichever is chosen, an explicit test asserts that a highly selective (small-tenant)
filter still returns a full in-scope top-k when that many in-scope rows exist — the
recall guarantee this section claims must be *verified*, not inferred from the
predicate living in `WHERE`. The exact-scan alternative (drop the ANN index) is
noted and rejected on latency grounds. The check pgvector version supports iterative
scan is a deployment prerequisite (§2.5 rollout).

`BaseVectorStore.search(...)` grows a structured parameter (the composed
scope+filters object) replacing the bare `parent_doc_id`. `PgVectorStore.search`
translates it to parameterized conjuncts on the metadata JSONB, e.g.:

- tenant: `metadata->>'organization_id' = :org`
- source: `metadata->>'source' = ANY(:sources)`
- document_type: `metadata->>'document_type' = ANY(:types)`
- organizational_unit: `metadata->>'organizational_unit' = ANY(:units)`
- date: `safe_to_date(metadata->>'doc_date') BETWEEN :date_from AND :date_to`
  (each bound applied only when present; the conversion returns `NULL` on any
  non-valid value so a malformed or impossible legacy value fails closed instead of
  raising, and no bare `::date` cast is evaluated over unvalidated text — see 2.4 /
  codex-2 R7)
- parent_doc_id: existing `parent_doc_id = :doc_id`

These JSONB `metadata->>'...'` / `ANY(:list)` shapes are **the pgvector mapping
only** — one example of the translation each store owns (codex M7). The contract the
service and tool see is backend-neutral field names and semantics; OpenSearch maps
the same fields to keyword/date fields and a bool/filter query.

All values are bound parameters (no interpolation beyond the already-validated
table name — the store's existing rule). Supporting JSONB expression indexes are
added in `_ensure_collection` mirroring the existing hash-index pattern (hash for
equality dimensions; for range, a **partial** btree on the same
`safe_to_date(metadata->>'doc_date')` expression, `WHERE` the result is non-NULL,
so the index build cannot raise on a bad row — codex-2 R7), with an `IF NOT EXISTS`
create and a backfill migration for pre-existing collections (same shape as
`0058_backfill_rag_lookup_indexes`).

**Both retrieval paths carry the identical object:**

- `RetrievalService.retrieve` composes `scope + filters` once and passes it to the
  vector `store.search`.
- **`_bm25_search` consistency fix:** thread the same composed object into
  `_bm25_search`, which forwards it to its `store.search` call. Because the BM25
  branch re-ranks the vector store's own `search` output, restricting that
  candidate corpus means fusion can never reintroduce an out-of-scope row. This
  closes the `parent_doc_id` gap and, with it, the tenant/business-filter gap on
  the hybrid path in one change.
  - **Honest naming (codex H3):** `_bm25_search` scores only the vector store's
    own candidate rows (`limit=min(limit*10,100)`), so it is **reranking over
    filtered vector candidates**, not corpus-wide keyword search. The security
    guarantee holds regardless (the candidates are pre-filtered), but the
    name/docstring will say what it is; a true corpus-wide keyword query is
    deferred and is where the OpenSearch adapter naturally lands.
- `retrieve_multi` takes **both** `RetrievalFilters` and `RetrievalScope` and
  threads them to every collection it visits (codex H4) — the multi-collection
  path ignores `filter` today, which this change fixes.

**The tenant conjunct is not only a search concern (codex-2 R2).** The shared
physical table is reached by more than `search()`. Today `find_existing_document`
(the ingest dedup/replacement lookup), `delete_document`, `get_documents`,
`get_document_chunks` and the chunk/document counts all query `rag_<name>` with
**no tenant predicate** (`vectorstore.py`, `ingestion.py`). The most dangerous is
the replacement path: `IngestionService` looks a document up by `source_path` /
`filename` / `content_hash` with no `organization_id`, then **deletes the returned
`parent_doc_id`** — so two tenants sharing a collection name and a source path can
have one tenant's ingest silently replace and delete the other's document. A
read-path-only tenant fix would leave this cross-tenant *write* clobber open. FA-039
therefore threads the trusted tenant scope through **every row-level operation on
the shared table** — dedup/replacement, deletion, listing, chunk fetch and counts —
not just `search()`. (The clean long-term alternative is a tenant-unique physical
namespace, e.g. `rag_<org>_<name>`; that is a larger migration and is noted, not
adopted, here — the conjunct-everywhere approach closes the hole without a table
rename.) The files-in-scope list (§3) is widened to name these call sites.

### 2.4 Date semantics and missing-field behavior

**Canonical document date field: `doc_date`** (ISO `date`), written on every chunk
via `DocumentMetadata`. Provenance precedence, documented in the tool/API contract
and `docs/reference/spec.md`/`capabilities.md`:

1. explicit author/uploader-supplied document date, else
2. the source's modified time (file mtime / S3 `LastModified` / Drive
   `modifiedTime`), else
3. ingestion time.

`doc_date` is a **pure calendar date**: any source *timestamp* is converted to UTC
first, then its date is extracted, and the value is **normalized to ISO
`YYYY-MM-DD` at ingestion** (codex M6). Because new ingests and the backfill store
only normalized values, the range cast cannot raise.

**The guard must be genuinely safe, not a regex (codex-2 R7).** The M6 regex
(`~ '^\d{4}-\d{2}-\d{2}$'`) still admits impossible-but-shaped values such as
`2025-99-99`, which raise on `::date`. Postgres does **not** guarantee AND-operand
evaluation order, so `regex AND value::date BETWEEN …` cannot be relied on to skip
the cast — and *creating* an expression index over `(metadata->>'doc_date')::date`
evaluates that cast over every legacy row, failing the migration itself on one bad
value. The design therefore uses a **conversion that cannot raise** rather than a
guard-then-cast: a `CASE` (or a helper) that returns a real `date` only when the
value passes full date validation and `NULL` otherwise, e.g. conceptually
`safe_to_date(metadata->>'doc_date')`. A row that yields `NULL` **fails closed**
(never matches a date filter), and the expression index and the WHERE predicate use
the **identical** safe expression (a partial index on the non-NULL result) so the
index build cannot raise either. A real typed `doc_date` column is the sturdier
alternative and is noted as the preferred shape if the migration cost is accepted;
either way no `::date` cast is ever evaluated over unvalidated text. Tests must
include **syntactically date-shaped but impossible dates** (`2025-99-99`), not only
malformed strings and missing keys.

Range is **inclusive `[date_from, date_to]`** on that calendar date. Either bound
may be omitted (open-ended range).

**Missing-field behavior — fail-closed for any supplied filter:**

- **Date:** when a date filter is supplied, a chunk with no `doc_date` (e.g. legacy
  chunks) does **not** match — a date filter is a positive assertion and a row that
  cannot prove it falls in range must not be returned. When no date filter is
  supplied, missing `doc_date` is unrestricted.
- **source / document_type / organizational_unit:** same principle. If the filter
  on dimension X is supplied and a chunk lacks X, it does not match X. If the
  filter is absent, dimension X is unrestricted.
- **Tenant (scope):** strictest and always applied. A chunk missing
  `organization_id` in metadata is **never** returned to a tenant-scoped caller
  (fail-closed). A backfill (2.5) writes `organization_id` onto existing chunks;
  until a given legacy collection is backfilled its chunks are invisible to
  tenant-scoped search — the safe default (silence, never leakage).

These behaviors are each covered by an explicit named test (see 4).

### 2.5 Ingestion — what to populate and preserve

Extend `DocumentMetadata` (`services/rag/models.py`) with **typed** fields (not
free-form `additional_info`): `organization_id`, `source`, `document_type`,
`organizational_unit`, `doc_date`. Because `_build_chunk_metadata` already dumps
`document.metadata.model_dump()` onto every chunk, adding typed fields
automatically **preserves them per chunk** with no change to the write path.

Provenance and trust:

- **`organization_id` is security-bearing and is written from trusted worker
  context only** — the org-scoped ingestion flows know `organization_id` /
  `KnowledgeBase.organization_id` (`worker/tasks/rag_tasks.py`). The uploader's
  `ingestion` form input and any model/user-supplied metadata **must not** be able
  to set it (defense in depth: a caller must not stamp a chunk with another
  tenant's id). This is injected in the worker/ingestion service, not the parser.
- **Not every ingestion path has a tenant (codex-2 R5).** The claim "the ingestion
  flow already knows `organization_id`" is **not universal**: the local-directory
  sync task deliberately ingests with `organization_id=None` (it names a path on
  the server, not a collection an organization owns — `rag_tasks.py`, the
  `SpendLedger()` with no org). Under mandatory tenant filtering those chunks would
  become permanently invisible to every tenant-scoped caller. The design's decision:
  such documents are **deployment-scoped, not tenant-scoped** — they carry no
  `organization_id` and are reachable **only** through the explicit unscoped
  maintenance path (2.2's separately named CLI/app-admin marker), never through an
  ordinary tenant-scoped search or agent tool. This is fail-closed by construction
  (a missing tenant is never leaked to a tenant caller) and it names the supported
  path rather than pretending every ingest has an org. A deployment that wants these
  documents tenant-searchable must (re-)ingest them under a real organization.
- `source`, `document_type`, `organizational_unit`, `doc_date` are business
  metadata derived from the connector/upload context and/or author input; these
  are non-security and may be author-supplied.
- **`organizational_unit` is a discovery filter, not an access boundary
  (self-review L6).** Its name invites treating it as departmental isolation, but it
  is author-supplied, non-security metadata and a caller can pass any value. Access
  is enforced solely by the tenant conjunct (FA-039) and per-document ACLs (FA-037);
  `organizational_unit` only *narrows discovery within* what the caller may already
  read. A deployment that needs a department to be a hard boundary must model it as a
  separate collection/tenant or through FA-037, never by relying on this filter. This
  is stated in the API/tool docs so it is not mistaken for a control.

Migration/backfill (heed the `rag-knowledge` JSONB trap): *adding* fields is safe
(missing keys take defaults, existing JSONB rows stay readable), and no existing
validation is *narrowed*, so stored rows are not invalidated. The **tenant** field,
however, is a security backfill, not a caveat (codex C2). The migration must:

1. assign ownership **only through a positive, unique join** from a chunk's
   `(collection_name, parent_doc_id)` to a `DONE` tracking row's
   `(collection_name, vector_document_id, organization_id)` — never by stamping a
   table wholesale with its sole current tenant (codex-2 R4). A table that backs
   only one current KB can still hold chunks from a **deleted** tenant, an
   incomplete tracking write, or a local/admin (`organization_id=None`) ingest, so
   "one current org" is not proof every chunk is that org's;
2. **quarantine everything the join does not positively resolve** — a chunk with no
   matching `DONE` row, an ambiguous match, or a row whose tracked org is NULL keeps
   `organization_id` unset so it fails closed (unsearchable) rather than being
   assigned a guessed tenant;
3. mark affected KBs **degraded** and surface that state through a **defined
   operator-visible surface (self-review M4)**: a per-KB `degraded` flag and a
   quarantined-chunk count on the `KnowledgeBase` read model, shown on the KB admin
   view and returned by the collection API, plus a one-line migration/report summary
   (tables scanned, chunks resolved, chunks quarantined, KBs degraded). "Surface that
   state" is not left to a log line — a document that was searchable and is now
   quarantined is invisible to its owner, so the degraded/quarantined state must be
   observable and actionable (re-ingest under a real organization clears it).

**Scope note (self-review M4).** This tenant backfill — shared-table detection,
positive-join ownership resolution, quarantine, degraded surfacing and the ordered
rollout below — is materially larger than the read/write filtering it protects and
carries the change's main operational risk. It should be tracked as its **own sized
task** (roughly `effort:l`) under FA-039 rather than folded silently into the filter
work, so the rollout gets its own review and verification.

**Deployment ordering matters (codex-2 R4).** The steps must run in an order that
cannot leave a window where new untagged chunks appear after the backfill: (a) ship
the tenant **dual-write** (new ingests stamp `organization_id`) and deploy it
everywhere; (b) drain/upgrade any old workers so nothing still writes untagged
chunks; (c) run the backfill and verify; (d) only then **enable mandatory tenant
read filtering**. Enabling read enforcement before old writers are drained would
either hide freshly-ingested documents (fail-closed but surprising) or, if
enforcement lagged, leak — so the read switch is last.

Rollout is fail-closed: unresolved/quarantined chunks are invisible to
tenant-scoped search, never leaked. There is no silent single-org backfill of a
shared *or* single-KB table — ownership is only ever the join's positive result.

### 2.6 Keeping the contract clean for a future OpenSearch adapter

- The filter contract is a **structured, typed object** (`RetrievalFilters` +
  `RetrievalScope`), never a SQL string or pgvector-specific DSL.
- Translation from structured object → backend query lives **inside each
  `BaseVectorStore` implementation**. The retrieval service composes and forwards;
  it builds no SQL. Adding a **vector** backend = implementing one `search()`
  translation + its ingestion mapping, with **zero** change to `RetrievalService`,
  the API route, the tool, or the filter schema.
- **The "zero change" claim is scoped honestly (codex-2 R8).** A single
  vector-oriented `search()` does **not** by itself deliver genuine OpenSearch
  lexical or native-hybrid search. Today the hybrid branch reranks the vector
  store's own candidates (2.3, H3) and first calls an **unscoped `get_documents()`**
  purely as a non-empty probe (`retrieval.py`) — which, on a shared table, also
  reads across tenants. FA-039's seam guarantees the *filter/scope contract* is
  backend-neutral, not that lexical/hybrid arrives free. So this section commits to:
  (a) removing the unscoped `get_documents()` probe (or giving it the same trusted
  scope), and (b) defining a **backend-neutral retrieval operation/mode** — vector,
  lexical, or native hybrid — in which **scope and filters are mandatory inputs for
  every candidate-producing query**, so no future backend can add a candidate source
  that skips enforcement. A true corpus-wide lexical/hybrid query remains deferred;
  the seam is what stays neutral.
- The abstract `search()` signature is backend-neutral, so the "both paths enforce
  the same restrictions" guarantee holds regardless of backend. For portability,
  `document_type` needs **one canonical definition**, not "mime/filetype *or*
  semantic type" (codex-2 R8) — the ambiguity breaks exact keyword filtering across
  backends; the design fixes it to the stored `filetype`/mime string and treats any
  richer semantic taxonomy as a later, separately-specified dimension.
  - **Confirm the product meaning with the issue owner (self-review M2).** FA-039
    lists "document type" as a business dimension, and a user may well expect
    *semantic* types (contract, invoice, policy) rather than a mime/filetype string.
    Fixing `document_type` to the stored filetype is the right *technical* canonical
    for portability, but if the tender's intent is semantic classification, that is a
    separate dimension (e.g. `document_category`) to be specified and populated — not
    silently satisfied by mime. This is flagged as an acceptance-criteria check to
    resolve before implementation, not assumed.
- The legacy scalar-string `filter` is retired; for backward compatibility a thin
  shim may map an incoming string to the typed field during a deprecation window —
  but it accepts **only a full-match `parent_doc_id == "<id>"` expression and
  rejects all other text** (codex-2 R9). Substring extraction (today's behavior)
  would silently discard any additional clauses a caller wrote, quietly *widening*
  the result versus the caller's intent; a full-match-or-reject shim cannot. No new
  backend assumptions travel through a string. This issue does **not** build
  OpenSearch — only guarantees the seam.
  - **Compatibility note (self-review L5).** Because only `parent_doc_id == "<id>"`
    was ever honored, any existing caller sending a *different* filter string does
    nothing today but will be **rejected (422)** by the full-match shim. This is a
    deliberate, safe behavior change (a silently-ignored filter that reads as
    honored is worse), but it is a change: it must be called out in the API docs and
    the changelog/release notes, and the deprecation window communicated to
    programmatic API consumers.

### 2.7 Boundary with FA-037 (document ACL)

- **What "permissions" means in FA-039 (codex-2 R3).** Issue #1593 lists
  *permissions* among the filter dimensions. FA-039 delivers permission
  enforcement at **two** layers — collection-level read access
  (`CollectionAccessService`, already in place) **and** the new server-derived
  **tenant** conjunct — but it deliberately does **not** ship per-document ACLs;
  that is FA-037's scope (below). This split is a recorded decision, not an
  oversight: the `authorized_document_ids` slot is the plug, and its
  empty-denies-all semantics (2.1/2.2) mean that when FA-037 wires a resolver, a
  subject authorized for no documents (or a resolver that fails) denies access
  rather than exposing the tenant. If #1593's acceptance criteria are read to
  require *per-document* permission filtering inside FA-039 itself, that is a scope
  escalation to raise with the issue owner — it is not silently in this design.
- **FA-039 delivers:** the typed filter contract, the server-derived **tenant**
  scope, and the enforcement seam — a `RetrievalScope` object the store ANDs into
  every query on both the vector and BM25/hybrid paths. The minimum security
  conjunct shipped here is tenant (`organization_id`), layered on top of the
  existing collection-level access (`CollectionAccessService`).
- **FA-037 owns** per-document ACLs (which specific documents a subject may read
  within a tenant). `RetrievalScope` carries an explicit
  `authorized_document_ids` / auth-predicate slot so FA-037 plugs its ACL
  resolution into retrieval without reworking it. FA-039 does not compute
  per-document grants and does not replace FA-037.
- **`parent_doc_id` is a narrowing hint, never authority (codex M5).** A caller
  passing `parent_doc_id` can only reach documents already inside a collection it
  may read; the id does not grant access. When FA-037 populates
  `authorized_document_ids`, `parent_doc_id` is **intersected with** it — an id
  outside the authorized set matches nothing. In FA-039 the authority is
  collection-level read (`CollectionAccessService`) plus the tenant conjunct.

## 3. Files in scope (for the later, deferred plan)

- `app/schemas/rag.py` — `RetrievalFilters`, extend `RAGSearchRequest`.
- `app/services/rag/models.py` — extend `DocumentMetadata`; likely a `RetrievalScope`
  + composed-filter model (or a dedicated `rag_filters` module).
- `app/services/rag/vectorstore.py` — `search()` signature + WHERE translation +
  `_build_chunk_metadata` + `_ensure_collection` indexes; **and the tenant conjunct
  on every other row-level op on the shared table** (codex-2 R2):
  `find_existing_document`/`_first_document`, `delete_document`, `get_documents`,
  `get_document_chunks`, and the chunk/document counts.
- `app/services/rag/ingestion.py` — the replace/dedup path must pass trusted scope
  into the existing-document lookup so it cannot delete another tenant's document
  (codex-2 R2).
- `app/services/rag/retrieval.py` — compose scope+filters; **`_bm25_search` fix**;
  remove/scope the unscoped `get_documents()` probe (codex-2 R8);
  `retrieve` / `retrieve_multi` threading.
- `app/api/routes/v1/rag.py` — build `RetrievalScope` from `ctx`; request carries
  only business filters.
- `app/agents/capabilities/knowledge/_toolset.py`, `_search.py`,
  `_capability.py` — expose whitelisted business filters on the tool; build scope
  from `AgentDeps`.
- `app/worker/tasks/rag_tasks.py` / ingestion service — inject `organization_id`
  and business metadata at ingestion.
- Alembic backfill migration for tenant metadata + JSONB indexes.
- Docs: `docs/reference/capabilities.md`, `docs/reference/spec.md`, `docs/api.md`.

## 4. Test surface (acceptance-aligned, to be written in the deferred plan)

- **Combined filters** narrow correctly (source AND type AND date; OR within a
  multi-value field).
- **Missing metadata:** chunk without `doc_date` excluded under a date filter,
  included when none; same per dimension; tenant-missing chunk excluded always.
- **Cross-tenant denial:** org A cannot retrieve org B chunks in a shared-named
  collection; a supplied filter cannot reach org B.
- **Access-widening attempt:** a business filter cannot set/override tenant;
  parent_doc_id can only narrow; an `organization_id` (or any unknown) key in a
  filter body is **rejected** by `extra="forbid"` (codex-2 R9).
- **Empty-set semantics (codex-2 R1):** an empty business filter list is rejected;
  a populated-but-empty `authorized_document_ids` returns nothing (never "all").
- **Cross-tenant write clobber (codex-2 R2):** org A ingesting a file whose
  `source_path`/`filename`/`content_hash` collides with org B's document in a
  shared-named collection must **not** find, replace or delete org B's document.
- **Impossible-but-shaped date (codex-2 R7):** a chunk with `doc_date` =
  `2025-99-99` is excluded under a date filter and never raises (search returns,
  does not 500); the index build tolerates it too.
- **Both hybrid and non-hybrid** return the same restricted set; **`_bm25_search`
  regression** — the scope+`parent_doc_id` reach its `store.search`, and fusion
  reintroduces no out-of-scope row.
- **`retrieve_multi`** carries scope to every collection.
- **Filtered-ANN recall (self-review H1):** a highly selective (small-tenant) filter
  still returns a full in-scope top-k when that many in-scope rows exist — asserting
  the HNSW scan is not truncating in-scope results below `k`.
- **Filter-value discoverability (self-review M3):** a `source`/`organizational_unit`
  value absent from the corpus returns empty, and the facet/affordance list omits it
  (so the model can only choose values that exist).
- API/tool contract documented; docstrings carry the filter grammar and date
  semantics.

Tests follow `.claude/rules/testing.md` (anyio, refusal-first, assert the
consequence). `app/services/rag/*` is outside the coverage gate, so these
invariants are pinned by explicit named tests (per the `rag-knowledge` skill); the
tool/capability code in `app/agents/**` is at the 100% gate.

---

## 5. Codex critique and resolutions

Codex (`gpt-5.5`, read-only) reviewed the design above. Its default model errored
for this account, so the run used `-m gpt-5.5`. Seven findings, all **accepted**;
the design sections above are amended accordingly and the deltas are recorded here.

**C1 (Critical) — a `None` scope must not silently disable tenant filtering.**
Every `organization_id` in `retrieval.py`/`vectorstore.py` is optional today, so a
caller that keeps a legacy path gets no tenant conjunct. *Accepted.* Amended 2.2/2.3:
tenant-scoped retrieval (API route and agent tool) **requires a non-null
`RetrievalScope` with a non-null `organization_id`; there is no default and no
fallback to an unscoped search.** A single explicit, separately named system/CLI
path (e.g. `rag-search` maintenance, app-admin) may pass an "unscoped" marker, and
that path is the only one allowed to; it is covered by its own test asserting no
ordinary caller can reach it. The store treats "no scope" as an error, not as
"return everything".

**C2 (Critical) — backfill of the tenant field is a security step, not a caveat.**
"Flag for manual resolution" is too weak for shared-name multi-org tables.
*Accepted.* Amended 2.5: the migration must (a) detect vector tables backing more
than one `KnowledgeBase.organization_id`, (b) reconstruct per-chunk ownership from
the tracked `rag_documents` rows where the mapping is unambiguous, (c) **quarantine
ambiguous chunks** (leave `organization_id` unset so they fail closed and are
unsearchable), and (d) mark affected KBs **degraded** and surface that state.
Rollout ships fail-closed: unresolved chunks are invisible to tenant-scoped search
rather than leaked. No silent single-org backfill of a shared table.

**H3 (High) — name BM25 honestly; it re-ranks filtered vector candidates.**
`_bm25_search` scores only the vector store's own `search` output
(`limit=min(limit*10,100)`), so it is reranking over vector candidates, not a
corpus-wide BM25. *Accepted.* Amended 2.3: the *security* guarantee holds either
way, because the candidate set is now filtered before BM25 sees it — fusion cannot
reintroduce out-of-scope rows. But the design now states plainly that this is
**rerank-over-filtered-candidates**, not true keyword search; a genuine
corpus-wide keyword query is deferred (and is naturally where the OpenSearch
adapter earns its place). The name/docstring will say so.

**H4 (High) — `retrieve_multi` must carry both filters and scope.**
The multi-collection API path ignores `filter` entirely today. *Accepted.* Amended
2.3/3: `retrieve_multi` takes both `RetrievalFilters` and `RetrievalScope` and
threads them to every collection's `store.search`; tests cover multi-collection
business filters **and** tenant scope (not just single-collection).

**M5 (Medium) — `parent_doc_id` is a narrowing hint, never authority.**
Keeping `parent_doc_id` lets a caller target any guessed id inside a readable
collection. *Accepted.* Amended 2.1/2.7: `parent_doc_id` is **intersected with**
the scope's `authorized_document_ids` when FA-037 populates that slot, and is never
treated as authority. In FA-039 the authority is collection-level read
(`CollectionAccessService`) plus tenant; `parent_doc_id` only narrows within it.

**M6 (Medium) — define invalid/legacy date-value behavior and the UTC/date point.**
`(metadata->>'doc_date')::date` can raise on a malformed legacy/user value, and
"UTC" is odd for a calendar date. *Accepted.* Amended 2.4: `doc_date` is a **pure
calendar date**; any source timestamp is converted to UTC *before* its date is
extracted, and the stored value is **normalized to ISO `YYYY-MM-DD` at ingestion**.
The WHERE cast must not raise on a bad row: either the value is guaranteed
normalized (new ingests + backfill) or the predicate guards the cast
(`metadata->>'doc_date' ~ '^\d{4}-\d{2}-\d{2}$'` before `::date`, or a safe cast),
so a malformed legacy value fails closed (excluded) rather than 500-ing the search.

**M7 (Medium) — keep the contract backend-neutral, not SQL-shaped.**
The JSONB keys and `ANY(...)` examples leak pgvector assumptions into the contract.
*Accepted.* Clarified 2.1/2.6: the contract is **backend-neutral field names and
semantics** (`source`, `document_type`, `organizational_unit`, `date_from/to`,
`organization_id`, `parent_doc_id`, and the OR-within/AND-across rule). The JSONB
`metadata->>'...'` and `ANY(:list)` shown in 2.3 are **the pgvector mapping only**,
one example of the translation each store owns; OpenSearch maps the same fields to
keyword/date fields and a bool/filter query. Nothing SQL-shaped appears in the
schema the service or the tool sees.

**Rejected:** none. All seven are in scope for FA-039 and improve either the
security guarantee or the extensibility seam without expanding beyond the issue.

**Deferred (explicitly, per instruction):** the implementation plan. This document
is the general design only; the step-by-step plan, task breakdown and code are not
produced here.

---

## 6. Second review round (gpt-5.6-sol)

A second read-only codex pass (`-m gpt-5.6-sol`, run header confirmed
`model: gpt-5.6-sol`) re-reviewed the amended design, told to focus on **new or
still-unresolved** problems and not to restate round-one resolutions. Nine findings
(eight ranked + one hardening item). Each was verified against the code before a
verdict; nothing was accepted on the model's word alone. Round-one decisions (C1,
C2, H3, H4, M5, M6, M7) stand — none was overturned; R7 *sharpens* M6's date guard.

**R1 (Critical) — empty set defined as "allow all".** The doc said a `None`/empty
business field and an empty `authorized_document_ids` impose "no restriction".
*Verified:* the wording did conflate `None` with `[]`, and for an authorization
allow-list `[]` naturally means "may read nothing" — reading it as "everything" is a
fail-open. **Accepted.** Amended 2.1/2.2: tri-state made explicit — business
`None` = not applied, non-empty = allow-list, **empty = validation error**;
authorization `None` = slot unset, **populated-empty = match nothing**
(empty-denies-all). Test added in §4.

**R2 (Critical) — tenant isolation covered search but not the other row-level ops.**
*Verified in code:* `find_existing_document`/`_first_document`, `delete_document`,
`get_documents`, `get_document_chunks` and counts query `rag_<name>` with no
`organization_id` predicate (`vectorstore.py`); worst, `IngestionService`'s replace
path looks a document up by `source_path`/`filename`/`content_hash` **unscoped** and
then `delete_document`s the returned `parent_doc_id` (`ingestion.py`) — a real
cross-tenant *write*/delete clobber on a shared collection name. The round-one design
only scoped the read path. **Accepted.** New paragraph in 2.3 requires the tenant
conjunct on **every** row-level op; §3 now names `ingestion.py` and the specific
`vectorstore.py` methods; §4 adds the write-clobber test. (Tenant-unique physical
tables noted as the heavier alternative, not adopted.)

**R3 (High) — "permissions" not fully delivered.** #1593 lists *permissions* as a
dimension; FA-039 ships tenant + collection access and defers per-document ACLs to
FA-037. *Verified:* this is a deliberate, already-recorded boundary (2.7), not a
silent gap — collection access + tenant *are* permission enforcement, just not
per-document. **Accepted in part:** the demand to build a full per-document resolver
now is **rejected** as out-of-scope for FA-039 (it is FA-037's charter, and the doc
is design-only). What was warranted — an explicit statement of *which* permission
layers FA-039 delivers vs defers, tied to the empty-denies-all slot, and a flag that
a per-document reading of #1593's criteria is a scope escalation to raise with the
issue owner — is added to 2.7.

**R4 (High) — backfill can misassign historical/orphaned chunks.** *Verified:* a
table with one *current* KB org can still hold chunks from a deleted tenant, an
incomplete tracking write, or a local (`organization_id=None`) ingest, so the
round-one step "detect tables backing more than one org" implied single-org tables
could be stamped wholesale. **Accepted.** 2.5 rewritten: ownership is assigned
**only** by a positive, unique join from `(collection_name, parent_doc_id)` to a
`DONE` tracking row's `(vector_document_id, organization_id)`; everything else is
quarantined; and an explicit deployment order (dual-write → drain old workers →
backfill/verify → enable mandatory read filtering) is specified so no untagged
chunks appear after the backfill.

**R5 (High) — not every ingestion path has a tenant.** *Verified in code:* the
local-directory sync task ingests with `organization_id=None` and a no-org
`SpendLedger` (`rag_tasks.py`); the round-one claim "the ingestion flow already
knows `organization_id`" was not universal, and such chunks would vanish under
mandatory tenant filtering. **Accepted.** 2.5 now states these are
deployment-scoped (no `organization_id`), reachable **only** through the explicit
unscoped maintenance path, never tenant-scoped search — fail-closed, and named
rather than glossed.

**R6 (High) — `parent_doc_id` lacks a canonical ID namespace.** *Verified:* chunk
`parent_doc_id` is the parser `Document.id` (`models.py`), recorded on the
relational row as `RAGDocument.vector_document_id` (`String(255)`), which is *not*
the `RAGDocument` PK UUID (`rag_document.py`). Comparing the wrong namespace would
make permission intersection and the backfill silently match nothing. **Accepted.**
2.1 now states filters and `authorized_document_ids` carry **vector document ids**,
a trusted relational id must be translated to its `vector_document_id` first, and a
typed `VectorDocumentId` is preferred over bare `str`.

**R7 (High) — the date guard/index is not reliably fail-closed.** *Verified:* the
M6 regex `^\d{4}-\d{2}-\d{2}$` still admits `2025-99-99` (raises on `::date`);
Postgres does not guarantee AND-operand order, so `regex AND ::date` can still
evaluate the cast; and building an expression index over `(…)::date` evaluates the
cast on every legacy row, failing the migration itself. This **sharpens M6** (which
stands as the normalization/UTC decision) rather than overturning it. **Accepted.**
2.3/2.4 replace the guard-then-cast with a **non-raising conversion**
(`safe_to_date(...)` returning `NULL` on any non-valid value); the range predicate
and a **partial** btree index use the identical safe expression; a real typed
`doc_date` column is noted as the sturdier option; §4 adds an impossible-date test.

**R8 (Medium) — the OpenSearch/hybrid seam is overstated.** *Verified:* a single
vector-oriented `search()` does not deliver genuine lexical/native-hybrid search
"with zero change", and the hybrid branch first calls an **unscoped
`get_documents()`** probe (`retrieval.py`) that, on a shared table, reads across
tenants. **Accepted.** 2.6 scopes the "zero change" claim to *adding a vector
backend*, commits to removing/scoping the unscoped probe, requires a
backend-neutral retrieval **mode** (vector/lexical/hybrid) where scope+filters are
mandatory for every candidate query, and fixes `document_type` to one canonical
definition (stored `filetype`/mime) instead of "mime *or* semantic type".

**R9 (Medium, hardening) — reject unknown filter fields; full-match the legacy
shim.** *Verified:* the repo `BaseSchema` does **not** set `extra="forbid"`
(`base.py`), so a smuggled `organization_id` on a filter body would be silently
dropped rather than rejected; and the current shim regex-*extracts* a substring, so
extra clauses a caller wrote are silently discarded. **Accepted.** 2.1 sets
`extra="forbid"` on `RetrievalFilters`; 2.6 requires the shim to accept only a
full-match `parent_doc_id == "<id>"` and reject all other text; §4 adds the
unknown-field rejection test.

**Rejected / partial:** only R3 is partial — its clarification is accepted, but its
demand to implement per-document permission resolution now is rejected as FA-037's
scope and outside a design-only change. No finding was rejected outright.

**Still design-only.** This round amends design sections and records verdicts; it
adds **no implementation plan**, no task breakdown and no production code. The plan
remains deferred per instruction.

---

## 7. Optional retrieval-quality enhancements (NOT part of FA-039 delivery)

These are retrieval-quality options that layer **on top of** the FA-039 contract;
they are **not** in scope for issue #1593 and must not be bundled into its PR
(FA-039 is a committed tender item with a tight security contract of its own). They
are recorded here because the FA-039 seam is what makes them safe and cheap to add
later, and each is tracked by its own GitHub issue. This section is design intent
only — no implementation plan.

**The shared safety property.** Every enhancement below runs **after** the store
has applied `RetrievalScope` + `RetrievalFilters` (§2.3), operating only on the
already-authorized, already-filtered candidate set. So each can **reorder, expand
within scope, or subset** results — none can *widen* access. This is the same
narrowing-only invariant FA-039 establishes; these features inherit it by
construction rather than re-arguing it.

### 7.1 Reranker — as an option, either backend (issue #142)

After hybrid retrieval returns a wider candidate pool (e.g. top-50), rerank and
return the best top-k (e.g. 5–8). Opt-in, off by default, configured on the RAG
capability / agent spec, e.g. `rerank: {enabled, provider, model, candidate_pool,
top_k}`. **Both backends are offered as options** (the deployment/agent picks one):

- **LLM reranker** — a cheap, fast model (e.g. Haiku) scores candidate chunks for
  relevance, listwise in one call to bound latency/cost. No new infrastructure;
  reuses the existing model/provider plumbing and vault-sealed credentials.
- **Cross-encoder / rerank API** — a dedicated reranker (e.g. Cohere Rerank, Voyage
  rerank) via an API key sealed in the vault, or a local cross-encoder model. Best
  quality per token; cost is a configured external provider.

Runs strictly on the post-scope/filter candidate set (§2.3), so reranking a wider
pool never reaches an out-of-scope or cross-tenant chunk. Tracked by the existing
issue **#142 "Add a real reranker to RAG retrieval"** — no new issue.

### 7.2 Query analysis / expansion — as an option (issue #1649)

An opt-in pre-retrieval step (`query_analysis: {mode: off | keywords | multi_query
| hyde}`, default `off`) that improves recall on short/fuzzy queries: algorithmic
keyword extraction to strengthen the lexical/BM25 leg, LLM multi-query variants
unioned and fused, or HyDE. Every produced query still passes through the FA-039
scope+filter enforcement, so expansion adds candidate queries only within the
caller's tenant/collection scope. Tracked by **#1649**.

### 7.3 Self-query — as an option, direct FA-039 synergy (issue #1650)

An opt-in step (`self_query: {enabled}`, default off) where an LLM derives the
FA-039 **business** filters (`source`, `document_type`, `organizational_unit`,
`date_from/to`) from a natural-language question. Critically, it reuses FA-039's
type separation: the LLM emits **only** a `RetrievalFilters` object and can never
name `RetrievalScope` (tenant/authorization), which stay server-derived — so
self-query is not a new escalation vector, only a UX convenience that narrows within
existing scope. Inferred values run through the same validation (`extra="forbid"`,
closed-vocabulary, `date_from <= date_to`) as any caller-supplied filter. Tracked by
**#1650**.

### 7.4 Sibling follow-ups (issues only, not detailed here)

Two further retrieval-quality items were filed as separate issues and are noted for
cluster completeness; they are not designed here:

- **Parent-document / small-to-big retrieval** — match small chunks, return larger
  parent/window context, bounded and de-duplicated, within scope. **#1651**.
- **Result-quality controls** — MMR/near-duplicate dedup, a minimum-relevance
  threshold (complements FA-039's fail-closed stance), and configurable RRF
  weights/`k`. All operate on the post-scope candidate set. **#1652**.

**Sequencing suggestion.** Ship FA-039 (#1593) first, unbundled; then the reranker
(#142) as the highest-ROI, most isolated enhancement; then self-query (#1650), which
reuses this contract most directly; then #1649/#1651/#1652 as independent smaller
wins. A unified opt-in config block on the RAG capability
(`retrieval: {rerank, query_analysis, self_query, parent_context, mmr, min_score}`)
keeps every option off by default and per-agent, consistent with "an agent is a
versioned spec."

---

## 8. Third review round (self-review) and resolutions

A design-level review (independent of the two codex passes, which concentrated on
security) read the amended document against issue #1593's acceptance criteria and
the actual store code. Six findings; all applied to the design above. The first is
grounded in code and changes what the store layer must do; the rest are contract,
rollout and documentation corrections. No implementation plan was added — still
design-only.

**H1 (High) — the "WHERE before top-k" recall guarantee does not hold under HNSW.**
*Verified in code:* the store builds a **pgvector HNSW** index and searches with
`WHERE … ORDER BY embedding <=> :q LIMIT :k` (`vectorstore.py`). §2.3 argued that
putting restrictions in `WHERE` (vs a Python post-filter) makes top-k compute over
restricted rows — but a filtered HNSW scan walks the graph within `hnsw.ef_search`
and can return **fewer than k in-scope rows even when more exist deeper**, the same
failure it warns against. With the tenant conjunct now mandatory and selective on a
shared table, this is a common-path risk. **Amended §2.3** to require an explicit
mitigation (iterative index scan / raised `ef_search` / per-tenant partitioning or
partial index), make the pgvector-version prerequisite part of rollout, and **added a
recall test to §4** asserting a small-tenant filter still returns a full in-scope
top-k.

**M2 (Medium) — `document_type` may not mean what the tender expects.** Fixing it to
the stored filetype/mime is right for cross-backend portability, but the issue's
"document type" may intend *semantic* classes (contract, invoice). **Amended §2.6** to
flag this as an acceptance-criteria check to resolve with the issue owner, and to name
a separate `document_category` dimension if semantic typing is required — not silently
satisfied by mime.

**M3 (Medium) — filter values are not discoverable.** `source`/`organizational_unit`
are free-form; a guessed value returns silently empty (fail-closed), which makes the
filters practically unusable by the model. **Amended §2.1** to require a
tenant/collection-scoped facet affordance (distinct in-scope values) surfaced to the
tool, with a **§4 test** that an absent value returns empty and is omitted from the
facet list.

**M4 (Medium) — the tenant backfill is the biggest risk and its "surface that state"
was undefined.** **Amended §2.5** to define the operator-visible surface (per-KB
`degraded` flag + quarantined-chunk count on the KB read model and collection API,
plus a migration report) so an owner can see and clear a now-invisible document, and
to recommend the backfill be tracked as its **own sized task (~`effort:l`)** with its
own review rather than folded into the filter work.

**L5 (Low) — a previously-ignored filter string now 422s.** The full-match shim
rejects any non-`parent_doc_id` string that was silently ignored before. **Amended
§2.6** to require this behavior change be documented in the API docs and
changelog/release notes and communicated to programmatic consumers.

**L6 (Low) — `organizational_unit` could be mistaken for an access boundary.**
**Amended §2.5** to state explicitly that it is a discovery filter only; access is the
tenant conjunct (FA-039) plus per-document ACLs (FA-037), and a hard departmental
boundary must be modeled as a separate collection/tenant or via FA-037.

**Rejected:** none. All six are in scope for a correct FA-039 (H1 is a store-layer
correctness fix; M2 is a scope-confirmation gate; M3/M4 close usability and rollout
gaps; L5/L6 are documentation duties). **Still design-only** — this round amends
design sections and adds test-surface bullets; it adds no implementation plan, task
breakdown or production code.
