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
| `parent_doc_id` | `str \| None` | restrict to one document (the existing capability, now typed) | — |

Semantics: **within a field, multiple values are OR; across fields, AND.** A
`None`/empty field imposes no restriction on that dimension. Validation:
`date_from <= date_to`; where a closed vocabulary exists (e.g. `document_type`
against known mime/types) reject unknown values with a field error via
`app/core/field_errors.py`. The model contains **no tenant field and no
authorization field** — those dimensions are structurally *inexpressible* here, so
a caller cannot even name them (see 2.2).

Whitelisting for the tool: the agent tool exposes only the whitelisted business
dimensions (`source`, `document_type`, `organizational_unit`, `date_from`,
`date_to`). `parent_doc_id` is not offered to the model (the model chooses *what*,
not *which stored id*); the API keeps it for programmatic callers. Every exposed
argument is optional and typed on the tool signature so PydanticAI validates it.

### 2.2 The server-trusted scope (`RetrievalScope`)

A separate structure built **only** from trusted context:

| Field | Source | Purpose |
|---|---|---|
| `organization_id` | `ctx.organization_id` (API) / `AgentDeps.organization_id` (tool) | the **tenant** conjunct — the security-bearing restriction |
| `authorized_document_ids` / auth predicate | server-derived (FA-037 slot) | per-document authorization; empty/absent in FA-039 → no extra narrowing beyond collection access + tenant |

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

`BaseVectorStore.search(...)` grows a structured parameter (the composed
scope+filters object) replacing the bare `parent_doc_id`. `PgVectorStore.search`
translates it to parameterized conjuncts on the metadata JSONB, e.g.:

- tenant: `metadata->>'organization_id' = :org`
- source: `metadata->>'source' = ANY(:sources)`
- document_type: `metadata->>'document_type' = ANY(:types)`
- organizational_unit: `metadata->>'organizational_unit' = ANY(:units)`
- date: `(metadata->>'doc_date')::date BETWEEN :date_from AND :date_to`
  (each bound applied only when present; the cast is guarded so a malformed legacy
  value fails closed instead of raising — see 2.4 / codex M6)
- parent_doc_id: existing `parent_doc_id = :doc_id`

These JSONB `metadata->>'...'` / `ANY(:list)` shapes are **the pgvector mapping
only** — one example of the translation each store owns (codex M7). The contract the
service and tool see is backend-neutral field names and semantics; OpenSearch maps
the same fields to keyword/date fields and a bool/filter query.

All values are bound parameters (no interpolation beyond the already-validated
table name — the store's existing rule). Supporting JSONB expression indexes are
added in `_ensure_collection` mirroring the existing hash-index pattern (hash for
equality dimensions; a btree on `(metadata->>'doc_date')::date` for range), with
an `IF NOT EXISTS` create and a backfill migration for pre-existing collections
(same shape as `0058_backfill_rag_lookup_indexes`).

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
only normalized values, the range cast cannot raise; the predicate still guards the
cast (a regex/​safe-cast check) so a malformed legacy value **fails closed**
(excluded) rather than 500-ing the whole search.

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
  context only** — the ingestion flow already knows `organization_id` /
  `KnowledgeBase.organization_id` (`worker/tasks/rag_tasks.py`). The uploader's
  `ingestion` form input and any model/user-supplied metadata **must not** be able
  to set it (defense in depth: a caller must not stamp a chunk with another
  tenant's id). This is injected in the worker/ingestion service, not the parser.
- `source`, `document_type`, `organizational_unit`, `doc_date` are business
  metadata derived from the connector/upload context and/or author input; these
  are non-security and may be author-supplied.

Migration/backfill (heed the `rag-knowledge` JSONB trap): *adding* fields is safe
(missing keys take defaults, existing JSONB rows stay readable), and no existing
validation is *narrowed*, so stored rows are not invalidated. The **tenant** field,
however, is a security backfill, not a caveat (codex C2). The migration must:

1. detect vector tables that back more than one `KnowledgeBase.organization_id`
   (the shared-name case);
2. reconstruct per-chunk ownership from the tracked `rag_documents` rows where the
   mapping is unambiguous, and write `organization_id`;
3. **quarantine ambiguous chunks** — leave `organization_id` unset so they fail
   closed (unsearchable) rather than be assigned to a guessed tenant;
4. mark affected KBs **degraded** and surface that state.

Rollout is fail-closed: unresolved/quarantined chunks are invisible to
tenant-scoped search, never leaked. There is no silent single-org backfill of a
shared table.

### 2.6 Keeping the contract clean for a future OpenSearch adapter

- The filter contract is a **structured, typed object** (`RetrievalFilters` +
  `RetrievalScope`), never a SQL string or pgvector-specific DSL.
- Translation from structured object → backend query lives **inside each
  `BaseVectorStore` implementation**. The retrieval service composes and forwards;
  it builds no SQL. Adding OpenSearch = implementing one `search()` translation +
  its ingestion mapping, with **zero** change to `RetrievalService`, the API route,
  the tool, or the filter schema.
- The abstract `search()` signature is backend-neutral, so the "both paths enforce
  the same restrictions" guarantee holds regardless of backend.
- The legacy scalar-string `filter` is retired; for backward compatibility a thin
  shim may map an incoming `parent_doc_id == "<id>"` string to the typed field
  during a deprecation window, but no new backend assumptions travel through a
  string. This issue does **not** build OpenSearch — only guarantees the seam.

### 2.7 Boundary with FA-037 (document ACL)

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
  `_build_chunk_metadata` + `_ensure_collection` indexes.
- `app/services/rag/retrieval.py` — compose scope+filters; **`_bm25_search` fix**;
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
  parent_doc_id can only narrow.
- **Both hybrid and non-hybrid** return the same restricted set; **`_bm25_search`
  regression** — the scope+`parent_doc_id` reach its `store.search`, and fusion
  reintroduces no out-of-scope row.
- **`retrieve_multi`** carries scope to every collection.
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
