# FA-023 — Editable agent categories & tags (issue #1592)

Design, Codex review round, and implementation plan.
Branch: `feat/fa023-agent-categories-tags`.

## 1. Problem

Tender requirement FA-023 wants agents to carry editable **categories** and **tags**
so people can discover and filter them. Name, description and avatar already exist.
The categories that appear in the capability and MCP catalogs are *tool* metadata and
are unrelated.

Scope (from the issue):
- Persist categories/tags and expose them on the relevant API schemas.
- Let authorized admins/editors maintain them in the agent UI.
- Filter agent discovery by categories/tags without leaking inaccessible agents or
  another tenant's data.
- Preserve existing agents; handle empty values and duplicate tags consistently.
- Keep import/export consistent with the chosen metadata model; add regression tests
  and update metadata docs.

## 2. The central decision — spec field vs. record metadata

**Decision: agent-record metadata, NOT an `AgentSpec` field.** Two mutable
`text[]` columns on `agents` (`categories`, `tags`), edited through a dedicated
command endpoint, exactly mirroring how `avatar_color` already works.

### Why not the spec

`AgentSpec` (`backend/app/agents/spec.py`, `SPEC_VERSION = 11`,
`model_config = ConfigDict(extra="forbid")`) is the versioned, portable definition of
*behaviour*. Its own docstring says it deliberately excludes anything about *where* an
agent runs and *who* may use it, because "the same spec can be exported, reviewed and
reused across organizations." The agent model reinforces this precedent for
display-only metadata — `avatar_url` and `avatar_color` are columns, not spec, with an
explicit comment:

> "Deliberately not part of the spec: the spec is what runs and what gets exported to
> git, and a picture changes neither."

Categories/tags are the same kind of fact as a picture: they change neither what runs
nor what a client's exported YAML means. Putting them on the spec would be wrong on
several axes:

1. **Versioning mismatch.** A spec field is frozen into every published
   `agent_versions.spec`. Retagging for discoverability would then require *publishing a
   new version* — contradicting the acceptance criterion "add, change and remove
   categories/tags, persisting after reload" (a cheap, immediate, non-publish edit, the
   way avatar already behaves).
2. **Format cost.** Every published agent and every client git repo holds a copy of the
   spec format. Even an additive optional field is a `SPEC_VERSION` bump + a stored-doc
   test; a record column touches none of that.
3. **Tenancy.** A tag taxonomy is an *organization-local* discovery aid. Baking it into
   a portable, cross-org artifact mixes an access/deployment fact into the behaviour
   contract the spec is careful to keep clean.
4. **Import/export.** Because avatar metadata is already excluded from the exported
   spec, keeping categories/tags off the spec makes YAML export/import **unchanged** —
   which is precisely the "import/export consistency" the issue asks for (see §9).

### Precedent to copy (record metadata path)

- Schema: `AgentAvatarColorRequest` — a command body (its field is always meant), not a
  partial `*Update`.
- Route: `PATCH /agents/{id}/avatar-color` → `set_agent_avatar_color`, **no route gate**
  (per-resource), delegates to the service.
- Service: `AgentRegistryService.set_avatar_color` → `self.get(ctx, agent_id,
  perm=Perm.AGENTS_EDIT)` (which runs grant-aware `resolve_access`), then
  `agent_repo.update(...)`.
- Read: surfaced on `AgentRead` (like `avatar_color`, `has_avatar`).

## 3. Data model

Two columns on `agents` (`backend/app/db/models/agent.py`):

```python
categories: Mapped[list[str]] = mapped_column(
    ARRAY(String(32)), nullable=False, server_default="{}"
)
tags: Mapped[list[str]] = mapped_column(
    ARRAY(String(32)), nullable=False, server_default="{}"
)
```

- **PostgreSQL `text[]`/`varchar[]` array**, not JSONB and not a join table.
  - vs JSONB: an array of scalars is the natural shape and gets clean array operators
    (`&&` overlap, `@>` contains) plus a straightforward GIN index.
  - vs a normalized `tags` + `agent_tags` join table: rejected as over-engineering for
    this scope. A join table earns its keep when you need a canonical per-org tag
    registry, rename-propagation, or usage counts — none of which FA-023 requires. It
    would add two tables, a repository, cascade rules and more migration surface for no
    acceptance-criterion benefit. Revisit only if a managed tag vocabulary is later
    requested.
- `NOT NULL DEFAULT '{}'` — existing agents get an empty array automatically; no data
  backfill loop needed, no nullable ambiguity between "no tags" and "unset".
- GIN indexes for filter performance:
  `ix_agents_categories` on `categories`, `ix_agents_tags` on `tags`.
- Declared on the model **and** in the migration (the model's own comment notes
  integration tests build the schema from the models, so constraints/indexes must exist
  in both).

### Normalization (duplicates / empties / casing)

A shared, pure core `_fold_labels(values: list[str]) -> list[str]` in
`app/schemas/agent.py` does the value-shaping, and **two entry points wrap it with the
policy their caller needs** (round-two Finding 2 — the two callers must not share one
raising helper). Core rules, applied in order:

1. **Trim** each item and collapse internal whitespace runs to a single space.
2. **Case-fold** with `str.casefold()` (not `str.lower()`) after
   `unicodedata.normalize("NFC", …)`, so visually identical NFC/NFD spellings and the
   full Unicode case map fold to one canonical form (round-two lower-severity item —
   `lower()` alone leaves `"ß"`/`"ss"` and NFC/NFD variants distinct, splitting a tag
   and defeating the plain GIN index). Labels stay Unicode; the fold is canonical, not
   ASCII-only.
3. **Drop empties** (an item that is empty after trimming disappears — this is how
   "empty values" are handled consistently).
4. **De-duplicate**, preserving first-seen order.

The two entry points differ only in how they treat an **over-length item** (> 32 chars
after trim) and **list cardinality**:

- **`normalize_labels_strict`** (write path) **raises `ValueError`** on an item that is
  **> 32 chars *after folding*** — inside a Pydantic `field_validator`, so it surfaces as
  a clean **422**, not a DB error. The length check is on the **final NFC + `casefold()`
  value that will actually be stored**, not on the trimmed input, because `casefold()`
  can *expand* text (`"ß"` → `"ss"`, `"İ"` → two code points): a 32-char input can fold
  to a > 32-char value, and checking the pre-fold length would let it through to the
  `String(32)` column as a DB error / 500 (round-three Finding 1). Cardinality is capped
  by the schema `Field(max_length=…)` (10 categories, 20 tags), also a 422.
- **`normalize_labels_query(values, *, max_items: int)`** (filter path) is **tolerant**:
  it **drops** an item that is over-length (measured on the same folded value) or empty
  rather than raising, and **caps the result to `max_items`** after dedupe. It takes the
  cap as an explicit argument — the single helper cannot otherwise know whether it is
  folding categories (10) or tags (20) (round-three Finding 1); the service passes
  `max_items=10` for `category` and `max_items=20` for `tag`. It never raises and it
  never **truncates** an item to 32 chars — truncation could turn an invalid label into a
  valid-but-unintended match (round-two Finding 2/3). A bad or oversized query param
  should quietly narrow to nothing on that item, not 400 the discovery page and not
  match something the caller never typed.

The `String(32)` column length and the `Field` count caps remain the backstops; the two
helpers make the refusal shape correct on each side (a 422 the form can show on write, a
silent narrowing on read) instead of leaking a `ValueError` out of the service as a 500.

**Casing decision: case-fold on write.** This makes de-duplication, filtering and
indexing all exact and consistent (`"Sales"` and `"sales"` are one tag, and a plain GIN
index answers the filter). The tradeoff is losing the author's original capitalization;
the UI can present a prettified/title-cased label for display. The rejected alternative —
preserve display casing but match case-insensitively — needs an expression GIN index over
a case-folded, immutable array-lowercasing wrapper of each element, which is materially
more complex for a cosmetic gain.

Because normalization lives in the schema validator, an unnormalized body (`["Sales",
"sales", "  "]`) is accepted and stored as `["sales"]` — duplicates and empties handled
by construction, and idempotent (re-normalizing changes nothing).

## 4. API surface

### Read

Add to `AgentRead` (`backend/app/schemas/agent.py`):

```python
categories: list[str]
tags: list[str]
```

**Required, not `default_factory=list`** (round-two Finding 4). Both columns are
`NOT NULL DEFAULT '{}'`, so the ORM row always carries a real list — a mapped column,
not a relationship, so `from_attributes` reads it with no lazy async load. Every
ORM-sourced `AgentRead` (detail via `AgentDetail.model_validate(agent)`, create, the
avatar/metadata mutation responses) supplies them for free. The one **hand-built**
constructor — `AgentRegistryService.list_agents` — must pass them explicitly (see §5
Codex #5 / §12 step 5); making the fields required means a missed hand-built path
**fails loud at serialization** instead of silently returning `[]` and hiding a
regression. (This departs from the defaulted `channels`/`shared_user_count` fields, which
default precisely because write endpoints skip paying for those extra queries; categories
and tags are cheap row columns that are always present, so "always meant" is the correct
contract.)

`from_attributes` maps them straight off the ORM row. They ride the existing
`AgentRead` used by both list and detail, so cards and the detail view both get them
with no extra query.

### Write (edit)

Command body + per-resource PATCH, mirroring avatar-color:

```python
class AgentMetadataRequest(BaseSchema):
    """Editable discovery metadata for an agent. A command body: both fields are
    always meant, and an empty list clears that facet."""
    categories: list[str] = Field(default_factory=list, max_length=10)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("categories", "tags", mode="after")
    @classmethod
    def _normalize(cls, v: list[str]) -> list[str]:
        return normalize_labels_strict(v)  # raises ValueError -> 422 on an item > 32 chars
```

```python
@router.patch("/{agent_id}/metadata", response_model=AgentRead)
async def set_agent_metadata(
    agent_id: UUID, data: AgentMetadataRequest, service: AgentRegistrySvc, ctx: Auth,
) -> Any:
    return await service.set_metadata(
        ctx, agent_id, categories=data.categories, tags=data.tags
    )
```

Service:

```python
async def set_metadata(
    self, ctx: AuthContext, agent_id: UUID, *,
    categories: list[str], tags: list[str],
) -> Agent:
    agent = await self.get(ctx, agent_id, perm=Perm.AGENTS_EDIT)  # grant-aware resolve_access
    return await agent_repo.update(
        self.db, agent=agent, update_data={"categories": categories, "tags": tags}
    )
```

No route gate (per-resource route → the service's `resolve_access` decides, so a Viewer
holding an explicit `edit` grant is not refused before the grant is consulted).

### Filter (discovery)

Add repeatable query params to `GET /agents` (collection route, keeps its existing
`require(Perm.AGENTS_VIEW)` gate):

```python
category: Annotated[list[str], Query()] = [],
tag: Annotated[list[str], Query()] = [],
```

The service normalizes the raw query params **once** with the tolerant
`normalize_labels_query` (never the raising strict variant — round-two Finding 2),
passing `max_items=10` for `category` and `max_items=20` for `tag` (round-three
Finding 1), then threads the already-normalized, already-bounded lists into
`list_agents(ctx, ..., categories=..., tags=...)` → `agent_repo.list_visible`. The
repository adds a `.where(...)` to **both** the data query and the count query, guarding
on the **normalized** result (round-one Codex #1) so a blank param like `?tag=%20`
normalizes to `[]` and simply applies no predicate:

```python
# categories / tags here are the tolerant-normalized lists the service passes down.
if categories:
    query = query.where(Agent.categories.op("&&")(categories))
    count_query = count_query.where(Agent.categories.op("&&")(categories))
if tags:
    query = query.where(Agent.tags.op("&&")(tags))
    count_query = count_query.where(Agent.tags.op("&&")(tags))
```

Semantics: **overlap (`&&`) within a facet = OR**; **categories AND tags across
facets**. Query values are folded the same way as stored values, so matching is
case-insensitive by construction. Order/count stay as they are.

**Filter cardinality is bounded** (round-two Finding 3). Repeatable query params are
otherwise unbounded — a caller could submit thousands of `?tag=` values, paying
disproportionate parse/normalize/SQL-parameter and GIN cost. `normalize_labels_query`
caps the normalized facet to the same 10 / 20 bounds the write path enforces, so a
runaway filter is trimmed rather than executed. (A cap, not a 400: over-supplying filter
values is not worth failing a discovery request over.)

## 5. Why filtering stays tenant- and permission-safe

The filter is a **narrowing** predicate layered on top of the query that already
enforces isolation — it can only remove rows from an already-authorized set, never add
one:

1. `list_visible` always starts with `Agent.organization_id == organization_id` (from
   `ctx`), so cross-tenant rows are never in scope.
2. Grant/visibility scoping is already applied: the service calls
   `visible_resource_ids(db, ctx, resource_type=AGENT, perm=Perm.AGENTS_VIEW)`; `None`
   → `see_all=True`, otherwise the returned ids feed the `shared_ids`/visibility
   predicate.
3. The new `categories`/`tags` `&&` predicates are **additional `AND` clauses on the
   same query and the same count query**. They compose with, and cannot widen, the org
   + grant predicates.

Therefore a tag filter can never surface an agent the caller could not already see, in
their own or any other tenant. This is the "filter narrows, authorization gates"
pattern the permissions rule wants; putting filtering server-side (not only in the
browser) keeps authorization and filtering in one place and correct beyond the first
page.

## 6. Permissions

No new permission. Reuse the existing catalog:
- **Edit** metadata = `Perm.AGENTS_EDIT`, enforced per-resource inside `set_metadata`
  via `self.get(..., perm=AGENTS_EDIT)` (grant-aware). A Viewer with an `edit` grant on
  one agent can tag that agent and nothing else.
- **View/filter** = `Perm.AGENTS_VIEW`, the existing collection gate on `GET /agents`,
  plus `visible_resource_ids`.

## 7. Migration & backfill

New revision `backend/alembic/versions/0078_agent_categories_tags.py`, `down_revision =
"0077_drop_allow_byo"` (current head). Docstring explains the spec-vs-column decision
(pointing at the avatar precedent).

```python
def upgrade() -> None:
    op.add_column("agents", sa.Column("categories", sa.ARRAY(sa.String(32)),
        nullable=False, server_default="{}"))
    op.add_column("agents", sa.Column("tags", sa.ARRAY(sa.String(32)),
        nullable=False, server_default="{}"))
    op.create_index("ix_agents_categories", "agents", ["categories"], postgresql_using="gin")
    op.create_index("ix_agents_tags", "agents", ["tags"], postgresql_using="gin")

def downgrade() -> None:
    op.drop_index("ix_agents_tags", table_name="agents")
    op.drop_index("ix_agents_categories", table_name="agents")
    op.drop_column("agents", "tags")
    op.drop_column("agents", "categories")
```

- **Existing agents preserved**: `server_default="{}"` fills every current row with an
  empty array — no data loop, no nullability ambiguity.
- Additive column, not a narrowing rule, so no data migration is required (contrast the
  OCR-language trap; that only applies when tightening an existing field).
- **Index-build locking, accepted deliberately** (round-two Finding 6). A plain
  `CREATE INDEX ... USING gin` takes a `SHARE` lock that blocks concurrent writes to
  `agents` while it scans the table. The scan is proportional to the row count, but
  `agents` is a low-cardinality table (an organization holds tens, not millions, of
  agents on this self-hosted, multi-tenant platform) and both new indexes start
  essentially empty, so the lock is held for a negligible window — this is accepted
  rather than worked around. `CREATE INDEX CONCURRENTLY` is deliberately **not** used:
  it cannot run inside Alembic's per-revision transaction, no existing migration in
  `alembic/versions/` uses it, and `tests/test_migrations.py` runs the chain
  transactionally forwards and back. If a deployment ever grows an `agents` table large
  enough for the lock to matter, the escape hatch is a follow-up revision that builds the
  indexes concurrently outside the transaction (`op.execute` with autocommit); it is out
  of scope here.
- Round-trip verified at the chain level by `tests/test_migrations.py` (forwards/back)
  and `make db-check` (model↔migration parity). The **per-revision** assertions
  (empty-array default on a pre-existing row, GIN `amname`, downgrade drops both) need a
  dedicated new integration test — `tests/test_migrations.py` does not exercise a single
  revision's data/index state (round-three Finding 4; see §13).

## 8. Frontend

Path map confirmed: filtering is currently **client-side, in-memory** in
`agents/page.tsx` (a `useMemo` over the fetched, already-tenant-scoped list); metadata
forms use controlled `useState` (no react-hook-form); there is **no builder Zustand
store** (draft lives in local state); avatar/colour are the editable-post-create
precedent in the detail header. Agent types live in `src/types/agents.ts`; the API is
called through the generic `apiClient` inside `src/hooks/use-agents.ts`.

Plan:

1. **Types** (`src/types/agents.ts`): add `categories: string[]` and `tags: string[]`
   to the `Agent` listing interface (NOT to `AgentSpec` — they are record metadata).
2. **Read/display**: render tag/category chips (existing `badge.tsx`) on the agent card
   and detail header.
3. **Edit surface** (post-create, like avatar): a small categories/tags editor in the
   detail page, gated on `can(Perm.agentsEdit)` (not rendered when absent), wired to a
   new `setMetadata` mutation in `useAgent` → `PATCH /agents/{id}/metadata`, invalidating
   `qk.agents.all()`. A new chips-input component under `src/components/agents/` (no
   existing tag-input primitive; build on `Input` + `badge`). Create-time tagging is out
   of scope for parity with avatar (avatar is also set after creation); note as a
   possible follow-up.

   **Editor gating — deliberately role-level, matching the whole Builder** (round-two
   Finding 1). The backend `set_metadata` is grant-aware (`resolve_access`), so a Viewer
   holding an explicit `edit` grant on one agent *can* edit its metadata **through the
   API**. The detail UI, however, gates every editing control on the page —
   `agents/[id]/page.tsx:261` computes `const canEdit = can(Perm.agentsEdit)`, and the
   draft editor, the model panel, the `AvatarColorPicker` and the `SharingPanel` all hang
   off it. The metadata editor gates on the **same** `canEdit`, exactly as the avatar
   precedent this design copies. Surfacing a metadata editor to a granted Viewer while
   the rest of the Builder stays hidden from them would be a *new* inconsistency, not a
   fix. The grant path remains a first-class capability via the API (and any future
   per-caller Builder surfacing would add a `can_edit` to `AgentRead` — mirroring the
   existing per-caller `can_run` — for the *whole* Builder at once, which is out of scope
   for FA-023). The frontend permission test therefore asserts "**no `agents:edit` role →
   editor absent**" (the avatar contract), not "Viewer + grant sees editor".
4. **Filter**: server-driven facet. Extend `qk.agents.list` and `useAgents` to pass
   `category`/`tag` params; add the facet control to `galleryControls` in
   `agents/page.tsx`. Keep the existing text/status filters as they are. (Text/status
   stay client-side; the tag facet goes to the server so it filters the whole set, not
   just the first page.)

   **One shared, side-effect-free canonicalizer feeds both the query key and the request
   params** (round-two lower-severity item). A single helper takes the raw facet arrays
   and returns a **sorted copy** (`[...arr].sort()`, never an in-place `.sort()` on React
   state — mutating the state array corrupts the render and can wedge the key). That one
   canonical output keys `qk.agents.list(includeArchived, categories, tags)` **and**
   builds the request. Repeated params go to `apiClient` as **tuple pairs**
   (`params: [["category","a"],["category","b"],["tag","x"]]`), because `RequestOptions.params`
   accepts `Record<string,string> | [string,string][]` and only the tuple form can carry
   a repeated key (`api-client.ts:15-17`) — the object form would collapse `category=a&category=b`
   to one value. Keying on the sorted arrays is what stops two different selections from
   sharing a stale cached page (round-one Codex #2).
5. **i18n**: keys in `pages.agents` (filter + editor labels) and `agents` if a
   create-form label is added; English source in `messages/en.json`. Product nouns stay
   English per the i18n rule.
6. **Permission proof**: `*.integration.test.tsx` asserting the editor control is absent
   without `agents:edit` and that the filter narrows the list.

## 9. Import / export consistency

- **Spec YAML export/import is unchanged.** Categories/tags are record metadata, exactly
  like `avatar_url`/`avatar_color`, so `to_yaml`/`from_yaml` and the round-trip contract
  (`spec == AgentSpec.from_yaml(spec.to_yaml())`) are untouched, and no `SPEC_VERSION`
  bump is needed. This is the deliberate consistency: portable behaviour stays portable;
  org-local discovery metadata stays out of it.
- **Export emits no metadata.** `GET /agents/{id}/spec.yaml` → `export_spec`
  (`agents.py:379`) serializes `AgentSpec.model_validate(agent.draft_spec).to_yaml()` and
  nothing off the row, so categories/tags never appear in an exported file. There is no
  other export surface that must learn about tags. If a record-level agent backup/export
  is added later, it should carry categories/tags alongside avatar for the same reasons.
- **Import does not touch metadata** (round-two Finding 5 — stated precisely). `POST
  /agents/{id}/spec.yaml` → `import_spec` → `save_draft` replaces only `draft_spec`
  (`agent_registry.py:1123`). Importing a YAML file into an **already-tagged** target
  therefore **preserves** that target's existing categories/tags — it neither clears nor
  overwrites them, because the file carries none. The earlier shorthand "a
  clone/export starts untagged" was imprecise about import; the exact contract is:
  - **export** never emits categories/tags;
  - **import** never clears or overwrites the target's categories/tags;
  - **clone alone starts untagged** (a fresh row, §11 Codex #6).
  These three are pinned by regression tests (§13), not asserted rhetorically.

## 10. Alternatives considered (summary)

| Axis | Chosen | Rejected & why |
|---|---|---|
| Home | Record columns | Spec field — freezes into versions, forces publish-to-retag, `SPEC_VERSION` bump, pollutes portable artifact |
| Storage | `text[]` + GIN | JSONB (less natural for scalar lists); join table (over-engineered for scope) |
| Casing | Lower-case fold | Case-preserving + `lower()` expression GIN index (complex for cosmetic gain) |
| Facet count | Two columns (categories, tags) | Single free-form list — issue explicitly names both as distinct facets |
| Filter location | Server-side query params | Browser-only `useMemo` — only filters the fetched page, splits authorization from filtering |

---

## 11. Codex review round

`codex exec` was initially unavailable (models-cache parse error + a default model
rejected for this account); it ran successfully pinned to `gpt-5.5`, medium effort. It
called the core decision (record metadata over `AgentSpec`) sound and the tenant/permission
story solid, and raised six issues. **All six accepted** — resolutions folded into the
plan below.

| # | Sev | Finding | Resolution |
|---|---|---|---|
| 1 | High | Filter predicate guards `if categories:` **before** `normalize_labels`, so `?tag=%20` is truthy, normalizes to `[]`, and `tags && '{}'` matches **nothing** (silently empties the list). | **Normalize first, then guard on the normalized result.** Compute `norm_cat = normalize_labels(category)` / `norm_tag = normalize_labels(tag)` in the service, pass them down, and apply the `&&` predicate only when the normalized list is non-empty. |
| 2 | High | Making the facet server-driven without expanding the React Query key lets different category/tag selections reuse stale cached results. | **Expand `qk.agents.list`** to a stable, normalized+sorted filter shape: `list(includeArchived, categories, tags)` keying on `[...,"list",includeArchived, sortedCats, sortedTags]`. `useAgents` takes the facet and threads it into both the key and the request params. |
| 3 | Med | `Field(max_length=10/20)` caps **list length**, not item length; an overlong label would hit `String(32)` as a 500/DB error, not a clean 422. | **The write normalizer enforces per-item length itself** (raise `ValueError` → Pydantic 422 for an item > 32 chars, after trim). The list-count cap stays as `max_length` on the field; the two caps are documented as distinct. Filter-side normalization narrows rather than raising (a bad query param should not 400 the discovery page). **Refined by round-two Finding 2**: the write and filter paths use two separate helpers (`normalize_labels_strict` / `normalize_labels_query`) so the service never leaks a `ValueError` as a 500, and the filter path **drops** an over-length item rather than truncating it. |
| 4 | Med | Model snippet only adds columns; GIN indexes must also be declared on the model (`__table_args__`), not just the migration, or model-built test schemas miss them and `make db-check` can drift. | **Add `Index("ix_agents_categories", "categories", postgresql_using="gin")` and the tags equivalent to `Agent.__table_args__`**, import `ARRAY`, `Index`. Implementation step 1 spells this out. |
| 5 | Med | `AgentRead` rows in `list_agents` are **constructed by hand** (not `from_attributes`), so adding fields to the schema alone leaves list cards without them. | **Add `categories=agent.categories, tags=agent.tags` to the `AgentRead(...)` construction** in `AgentRegistryService.list_agents`. Called out as its own implementation step. Detail path (`AgentDetail`/`get`) does use `from_attributes` and needs no change beyond the schema field. |
| 6 | Low | Clone copies the draft spec only, not row metadata; users might expect tags to travel with a clone. | **Documented decision: a clone starts untagged**, consistent with avatar metadata (a clone also starts with no avatar). Noted in the docs update and in a clone regression assertion. |

No findings rejected.

## 12. Implementation plan (ordered)

Each step maps to files and notes the coverage/parity gate it must satisfy.

**Which touched modules are actually under the 100% gate** (round-three Finding 3 —
verified against `backend/pyproject.toml [tool.coverage.run] include` and
`frontend/vitest.config.ts`). Only **`app/services/agent_registry.py`** among the backend
files touched here is in the gate's `include` list. The model (`app/db/models/agent.py`),
schema (`app/schemas/agent.py` — where the normalization helpers live), repository
(`app/repositories/agent.py`) and route (`app/api/routes/v1/agents.py`) are **not** in
`include`, so the gate does not measure them; the earlier "changes land in existing
covered files" was wrong. On the frontend, `src/hooks/**`, `src/lib/**` and
`src/components/agents/**` **are** gated (so the hook, the query-key helper and the new
chips-input/editor components must reach 100% branch coverage), but the two
`agents/**/page.tsx` files are **excluded** (pages are deliberately outside the gate).
Consequence: `agent_registry.set_metadata`/`list_agents` must be 100%-covered; the new
schema helpers and repository predicate must be **tested to full branch coverage anyway**
(unit + integration) even though the gate will not enforce it; page-level facet/empty
behavior is proven by integration tests, not the coverage number. This adds **no new
module**, so `[tool.coverage.run] include` / `[[tool.ty.overrides]] include` stay as they
are.

1. **Model** — `backend/app/db/models/agent.py`
   - Add `categories` and `tags` `Mapped[list[str]]` = `mapped_column(ARRAY(String(32)),
     nullable=False, server_default="{}")`.
   - Import `ARRAY` (from `sqlalchemy`) and `Index`.
   - Add two GIN indexes to `__table_args__`:
     `Index("ix_agents_categories", "categories", postgresql_using="gin")` and the tags
     equivalent. (Codex #4 — parity so model-built schemas match production.)

2. **Migration** — `backend/alembic/versions/0078_agent_categories_tags.py`
   - `down_revision = "0077_drop_allow_byo"`. Docstring: spec-vs-column rationale +
     avatar precedent + why `server_default='{}'` (existing rows).
   - `add_column` x2 (NOT NULL, `server_default="{}"`), `create_index` x2
     (`postgresql_using="gin"`); reverse in `downgrade`.
   - Verify: `make db-migrate` autogenerate as the draft, hand-review, then
     `alembic upgrade head` -> `downgrade -1` -> `upgrade head`; `make db-check` clean;
     `tests/test_migrations.py` green.

3. **Normalization helpers + schemas** — `backend/app/schemas/agent.py`
   - `_fold_labels(values)`: trim + collapse internal whitespace, NFC-normalize +
     `casefold()`, drop empties, dedupe (first-seen order). The pure value-shaping core.
   - `normalize_labels_strict(values)` (write): calls `_fold_labels`, then **raises
     `ValueError` on an item whose *folded* value is > 32 chars** (round-one Codex #3 ->
     clean 422). The check is on the stored (NFC + `casefold()`) value, not the trimmed
     input, because `casefold()` can expand length (round-three Finding 1).
   - `normalize_labels_query(values, *, max_items)` (filter): calls `_fold_labels`,
     **drops** an over-length item (measured on the folded value; never raises, never
     truncates), then **caps** to `max_items` (round-two Findings 2, 3). The cap is a
     parameter, not hard-coded — the service passes 10 for categories, 20 for tags
     (round-three Finding 1).
   - `AgentRead`: add `categories: list[str]` and `tags: list[str]` — **required**, no
     default (round-two Finding 4).
   - `AgentMetadataRequest(BaseSchema)`: `categories` (`max_length=10`), `tags`
     (`max_length=20`), each with a `mode="after"` `field_validator` calling
     `normalize_labels_strict`.

4. **Repository** — `backend/app/repositories/agent.py`
   - `list_visible(...)` gains `categories: Sequence[str] = ()`, `tags: Sequence[str] =
     ()` kw-only params (immutable defaults, not `list[str] = []` — ruff bugbear `B006`
     flags a mutable default argument; round-three Finding 9). Apply
     `Agent.categories.op("&&")(categories)` /
     `Agent.tags.op("&&")(tags)` to **both** `query` and `count_query`, **only when the
     (already-normalized) list is non-empty** (Codex #1). Caller passes normalized lists.

5. **Service** — `backend/app/services/agent_registry.py`
   - `set_metadata(ctx, agent_id, *, categories, tags)` mirroring `set_avatar_color`:
     `self.get(ctx, agent_id, perm=Perm.AGENTS_EDIT)` then `agent_repo.update`.
   - `list_agents(...)`: accept `categories`/`tags`, **normalize them once** via the
     tolerant `normalize_labels_query`, passing the per-facet cap explicitly
     (`max_items=10` for categories, `max_items=20` for tags — round-three Finding 1;
     empty stays empty, over-length dropped — round-two Findings 2, 3), then pass the
     normalized, bounded lists to `list_visible`.
   - Add `categories=agent.categories, tags=agent.tags` to the hand-built `AgentRead(...)`
     (Codex #5).
   - **Update the `_agent` unit-test mock** (`tests/test_agent_registry.py:125`): it is a
     bare `MagicMock`, so `agent.categories` / `agent.tags` return `MagicMock`s (not
     `list[str]`) and fail `AgentRead` validation once the hand-built row reads them. Set
     `agent.categories = []` and `agent.tags = []` in the helper (round-three Finding 5).
   - (Clone unchanged — starts untagged, Codex #6; assert in tests.)

6. **Routes** — `backend/app/api/routes/v1/agents.py`
   - `PATCH /agents/{id}/metadata` -> `set_agent_metadata` (no route gate), body
     `AgentMetadataRequest`, `response_model=AgentRead`.
   - `GET /agents`: add `category: Annotated[list[str], Query()] = []` and
     `tag: ... = []`; thread into `service.list_agents`. **Add `Annotated` to the
     `from typing import` line** — the module currently imports only `Any`
     (`agents.py:21`), so `Annotated` must be added or the route will not compile
     (round-three Finding 9). (The FastAPI `Query()`-defaulted list param is the framework
     idiom and is not the `B006` concern the repository signature is; if bugbear flags it,
     it takes a scoped `# noqa: B006` with a reason, the way route defaults elsewhere do.)

7. **Frontend types + hook + query key**
   - `src/types/agents.ts`: add `categories: string[]`, `tags: string[]` to `Agent`.
     **The listing always fills them, but declare them `categories?: string[]` /
     `tags?: string[]` (optional) to match the existing listing-filled fields**
     (`channels?`, `shared_user_count?`, `budget_monthly_usd?` are all optional in this
     interface even though the backend always sends them; round-three Finding 5). A
     **required** field here would break every typed `Agent` fixture that constructs a
     complete object and omits the listing-only fields — `agent-card.test.tsx`,
     `agents-filter.integration.test.tsx`, `delegate-list.test.tsx`,
     `subagents-section*.test.tsx`, `chat/agent-picker.test.tsx`. Render code reads them
     as `agent.tags ?? []`. (This differs from the *backend* `AgentRead`, which is
     required on purpose so a missed hand-built path fails loud — §4 Read; the frontend's
     concern is fixture ergonomics, and the interface already chose optional there.)
   - `src/lib/query-keys.ts`: `agents.list(includeArchived, categories=[], tags=[])`
     keyed on sorted facet arrays (Codex #2). One shared canonicalizer returns a **sorted
     copy** (`[...arr].sort()`, never mutating React state) used for both the key and the
     params (round-two lower-severity item).
   - `src/hooks/use-agents.ts`: `useAgents` accepts the facet, threads the canonicalized
     lists into the key and the `GET /agents` params, emitting the repeated `category` /
     `tag` keys as **tuple pairs** (`[["category","a"],["tag","x"]]`) since the object
     `params` form cannot repeat a key (`api-client.ts:15-17`); `useAgent` gains a
     `setMetadata` mutation -> `PATCH /agents/{id}/metadata`, invalidating `qk.agents.all()`.

8. **Frontend UI**
   - Chips-input editor component under `src/components/agents/` (new files, e.g.
     `metadata-editor.tsx` + a reusable `chips-input.tsx`, built on `Input` + `badge`),
     gated on `can(Perm.agentsEdit)` (not rendered otherwise); placed in the detail page
     beside the avatar controls; autosaves via `setMetadata`. **Specify the interaction
     up front** (round-three Finding 6): commit a chip on Enter and on blur; remove with
     Backspace-on-empty and a per-chip ✕; a disabled/pending state while the mutation is
     in flight; on failure surface the error and keep the local draft; the client sends
     the **raw** typed values and **re-renders from the normalized `AgentRead` the
     mutation returns** (so the server's fold/dedupe/clamp is what the user sees). The
     10/20 count and 32-char limits are shown as `maxLength`/disabled-add affordances,
     the server validator staying the backstop.
   - Category/tag chips on the agent card + detail header for display.
   - Facet control added to `galleryControls` in `agents/page.tsx`, driving the
     server-side params. **Declare the source of facet choices** (round-three Finding 6):
     the options are **not** derived from the current (already server-filtered) page —
     that set shrinks as you filter and cannot show labels past the first page. For
     FA-023's scope the facet is a **free-text / typed-token** control (the same chips
     input, or a simple text token list); a managed per-org vocabulary to populate a
     dropdown is the deferred join-table work (§15).
   - **Fix the list page's filter-state logic for server-side facets** (round-three
     Finding 2): `agents/page.tsx` currently derives "no agents exist" from
     `agents.length === 0`, gates the **Clear filters** CTA on `agents.length > 0`, and
     passes `total={agents.length}` to `AgentsCard`. Under a server facet a zero-match
     query returns an empty page and would wrongly show "No agents yet" /
     "Nobody has shared an agent" with **no way to clear the facet**. So: fold the active
     category/tag selection into the "filters active" decision (empty-state copy and the
     Clear-filters CTA), clear the facet in the existing `clearFilters` handler alongside
     `setFilter("all")`/`setQuery("")`, and render the count from the server `total`
     rather than `agents.length`. Covered by a zero-result facet test (§13).

9. **i18n** — `frontend/messages/en.json`
   - Editor + filter labels under `pages.agents`; a create-form label under `agents`
     only if create-time tagging is added (deferred by default). `pl.json` only if
     translated (en merged as fallback).

10. **Docs** — see §14.

## 13. Test plan

**Layering (round-three Finding 7).** The api layer (`tests/api/`) runs the route over
an **`AsyncMock` DB session** (`conftest.py` overrides `get_db_session` with
`mock_db_session`), so it proves route→service wiring, parsing, status codes and
permission gates — **not** SQL behavior. Anything that depends on the real `&&` operator,
the GIN index, the filtered `count`, tenant isolation or grant composition therefore
belongs in **`tests/integration/`** (a real Postgres), and service-logic assertions
(authorization via `resolve_access`, the hand-built `AgentRead`, the tolerant-normalize
call) belong in the **unit** layer (`tests/test_agent_registry.py`, repository mocked).
The bullets below are grouped accordingly rather than all under `tests/api/`.

Backend (anyio; the 100% gate covers only `agent_registry.py` here — see §12 intro; the
schema helpers and repository predicate are still tested to full branch coverage):

- **Unit — normalization helpers**: `_fold_labels` trims, collapses whitespace,
  case-folds, drops empties, dedupes preserving order, is idempotent, and **folds
  NFC/NFD and full-case-map spellings to one** (e.g. a composed vs. decomposed accented
  label dedupes; `casefold` folds where `lower` would not). `normalize_labels_strict`
  **raises on an over-length item** (-> 422 through the schema).
  `normalize_labels_query` **drops** an over-length item (no raise, no truncation) and
  **caps** to 10 / 20 (round-two Findings 2, 3).
- **Schema** — `AgentMetadataRequest` normalizes `["Sales","sales","  "]` -> `["sales"]`;
  count caps (11 categories / 21 tags) rejected; over-length item rejected 422;
  `AgentRead` **requires** `categories`/`tags` — a construction omitting them fails
  (round-two Finding 4).
- **API — edit route** (`tests/api/`, DB mocked): `PATCH /agents/{id}/metadata` reaches
  `set_metadata` with the parsed body and answers `AgentRead`; the route carries **no**
  `require(...)` gate; a caller the service refuses gets the mapped status. Over-length /
  over-count bodies are **422** at the schema (this is validator behavior, provable here
  or as a schema unit test).
- **Unit — service edit** (`tests/test_agent_registry.py`, repo mocked): `set_metadata`
  calls `self.get(..., perm=AGENTS_EDIT)` (grant-aware `resolve_access`) then
  `agent_repo.update`; a caller without `agents:edit` is refused and a Viewer **with an
  `edit` grant** succeeds (grant widens, not promotes). `list_agents` passes the
  tolerant-normalized, capped facet lists to `list_visible` and fills
  `categories`/`tags` on the hand-built `AgentRead`.
- **Integration — filter/discovery** (`tests/integration/`, real Postgres — the only
  layer that runs the real `&&`/GIN/count): `?tag=x` returns only matching visible
  agents; `?category=a&tag=b` ANDs across facets, multiple `tag` ORs within the facet;
  case-insensitive match; `?tag=%20` (blank) is a no-op returning the full visible list
  (Codex #1 regression); an **over-length query item is dropped, not a 500 and not a
  truncated match** (round-two Finding 2 regression); an over-supplied facet
  (> cap values) narrows without error (round-two Finding 3); `total` reflects the
  filtered count; set/change/clear (empty list) and duplicate/empty/mixed-case input
  round-trip **stored normalized** across a re-fetch.
- **Integration — tenant isolation on filter**: an agent in org B carrying tag `x` never
  appears in org A's `?tag=x`; a private/ungranted agent in the caller's own org carrying
  `x` does not appear for a caller who cannot see it (filter narrows the visible set
  only); a Viewer's `edit` grant lets them PATCH exactly one agent's metadata and a
  **cross-tenant** PATCH is a 404 even when the caller owns a same-named agent elsewhere.
- **Non-empty metadata round-trips every AgentRead path** (round-two Finding 4,
  round-three Finding 8): a tagged row shows its categories/tags through the **list**
  card, the **detail** response, and the **metadata-mutation** response — the required
  fields never serialize as a false `[]`. The other routes that answer `AgentRead`
  (create, draft-update, publish/rollback response, clone, avatar-color, archive/
  unarchive) all serialize the **ORM row via `from_attributes`**, so they carry the
  columns for free; add one representative **create-and-read-back** (and the
  **avatar-color** response) assertion to guard against a future hand-built or unrefreshed
  path silently regressing, rather than exhaustively re-testing each.
- **Import/export** (round-two Finding 5, `tests/api/`): `GET /agents/{id}/spec.yaml`
  never contains categories/tags; importing a spec into an **already-tagged** target
  leaves its categories/tags **unchanged** (import touches only the draft); the exported
  YAML re-imported into a fresh agent carries no metadata.
- **Clone**: cloning a tagged agent yields an untagged clone (Codex #6).
- **Route-gate contract**: `tests/api/test_platform_routes.py` — the new per-resource
  PATCH carries **no** `require(...)` gate; the collection `GET` keeps its
  `AGENTS_VIEW` gate.
- **Migration semantics** — needs a **new revision-specific test**, not the existing
  `tests/test_migrations.py` (round-three Finding 4). That file only runs the whole chain
  (`upgrade head`, `downgrade base`, the cycle, `current == head`); it never inserts a row
  at a revision or inspects a column/index. Add a test (integration, real Postgres) that:
  upgrades to **0077**, inserts a valid `agents` row, upgrades to **0078**, asserts both
  arrays default to empty on that pre-existing row and both indexes exist **with
  `amname = 'gin'`** (via `pg_index`/`pg_class`/`pg_am`), then downgrades to 0077 and
  asserts the columns and indexes are gone. Separately, a model-built-schema integration
  assertion verifies the two `Index(...)` entries are declared on `Agent.__table_args__`
  (Codex #4 parity). `make db-check` clean and the existing full-chain `test_migrations.py`
  still green cover the round-trip at the chain level.
- **Coverage-gate contract**: no new module is added, so `[tool.coverage.run] include`
  and `[[tool.ty.overrides]] include` stay unchanged (`test_coverage_gate.py` still
  passes). Note the changes land in a **mix** of gated (`agent_registry.py`) and
  **ungated** (`db/models/agent.py`, `schemas/agent.py`, `repositories/agent.py`,
  `api/routes/v1/agents.py`) files — the ungated ones are not measured by the gate but
  are still tested to full branch coverage here (round-three Finding 3). Run `make test`
  (backend + gate), `make test-frontend-cov` (frontend gate) and a frontend build before
  pushing.

Frontend (`*.integration.test.tsx`, Testing Library vs. mocked API; the gate covers
`hooks/**`, `lib/**`, `components/agents/**` but **not** the `agents/**/page.tsx` files —
round-three Finding 3, so the hook, query-key helper and chips-input/editor components
reach 100% and the page behavior is proven by integration tests):

- Editor control **absent** without the `agents:edit` role, **present** with it (not
  rendered-then-403) — the same role-level contract the avatar/draft controls hold
  (round-two Finding 1); the test does **not** assert a granted Viewer sees it.
- Editing submits normalized categories/tags to `PATCH /agents/{id}/metadata` and shows
  the resulting chips **from the returned `AgentRead`** (server-normalized, round-three
  Finding 6); a rejected mutation surfaces the error and keeps the draft.
- The facet control drives the request params and the query key changes with the facet
  (no stale cache, Codex #2); the filtered list renders only matching cards. Assert the
  repeated params reach the client as **tuple pairs** and that selecting a facet does not
  mutate the source array (round-two lower-severity item).
- **Zero-result facet** (round-three Finding 2): a facet selection that matches nothing
  shows the *filter-empty* copy (not "No agents yet"/"Nobody has shared an agent") and a
  working **Clear filters** action that resets the facet; the count reflects the server
  `total`.
- **i18n validation** (round-three Finding 10): the new keys pass the repository's
  message-catalog consistency check (en/pl parity as the rule requires), and the filter
  and editor controls expose accessible names (assert by role/name, not by test id).
- Assert on **data**, not chrome (empty-state trap).

## 14. Documentation

- `docs/concepts.md` — note categories/tags as mutable, org-local agent metadata
  (contrast the versioned spec), and that they are **not** part of the exported spec:
  export emits no metadata, import leaves the target's metadata unchanged, and only a
  clone starts untagged (round-two Finding 5), mirroring the avatar wording.
- `docs/console.md` — the agents listing/discovery section: filtering by category/tag and
  where the editor lives.
- `docs/api.md` — the `PATCH /agents/{id}/metadata` command and the `category`/`tag` query
  params on `GET /agents` (matching semantics: OR within a facet, AND across facets,
  case-insensitive).
- **Not** `docs/reference/spec.md` — it is generated from `AgentSpec` docstrings, and the
  spec is deliberately unchanged.
- `docs/ROADMAP.md` / `CHANGELOG.md` — an entry for FA-023 if the repo convention expects
  one (check `scripts/docs_drift.py` trigger map on the touched paths).

## 15. Out-of-scope / deferred (recorded, not built)

- Create-time tagging in the create dialog (parity with avatar, which is set post-create).
- A managed per-org tag vocabulary / autocomplete registry (would justify the join-table
  model; revisit if requested).
- Copying discovery metadata on clone (deliberately not done; §11 #6).

## 16. Second review round (gpt-5.6-sol)

A second `codex exec` review (`gpt-5.6-sol`, read-only, medium effort) was run against
this design after the first round (`gpt-5.5`) was already folded in, asked to focus on
**new or still-unresolved** problems. Each finding was verified against the actual code
before a verdict. Six ranked findings plus two lower-severity items.

| # | Sev | Finding | Verdict | Change |
|---|---|---|---|---|
| 1 | High | UI editor gated on role-level `can(Perm.agentsEdit)` contradicts the grant-aware backend (`set_metadata` uses `resolve_access`); a granted Viewer can call the API but not use the UI. Recommends adding a per-caller `can_edit` to `AgentRead`. | **Observation accepted, recommended fix rejected** | See below — gating is deliberately consistent with the whole Builder; §8 step 3 records the rationale, §13 keeps the "no role → absent" test. |
| 2 | High | The single raising `normalize_labels` is used by both the write validator (wants 422) and the service filter path; a `ValueError` in the service becomes a **500**, contradicting the round-one note that filter normalization "skips/truncates". | **Accepted** | Split into `normalize_labels_strict` (raises → 422) and `normalize_labels_query` (tolerant, drops, no truncation). §3, §4 filter, §12 steps 3/5, §13. |
| 3 | Med | Filter query params (`category`/`tag`) are unbounded while the write body caps at 10/20. | **Accepted** | `normalize_labels_query` caps the normalized facet to the same 10/20. §3, §4 filter, §13. |
| 4 | Med | `AgentRead.categories/tags` default to `[]`; since the columns are `NOT NULL`, a missed hand-built constructor would silently return false-empty metadata. | **Accepted** | Make both fields **required**; only the one hand-built path (`list_agents`) must supply them, ORM paths get them from `from_attributes`. §4 Read, §12 step 3, §13. |
| 5 | Med | "clone/export starts untagged" is imprecise: import (`save_draft`) touches only `draft_spec`, so importing into a tagged agent **preserves** its tags; and no import/export regression is planned. | **Accepted** | §9/§14 restated precisely (export emits none; import preserves; only clone starts empty) and §13 gains an import/export regression. |
| 6 | Med | Two plain `CREATE INDEX ... USING gin` block writes on `agents` during their scan; recommends `CONCURRENTLY` for zero-downtime. | **Accepted as documented decision** | `agents` is a low-cardinality table and `CONCURRENTLY` cannot run in Alembic's transactional migration (no such precedent in `alembic/versions/`); §7 records the accepted brief lock and the follow-up escape hatch. |
| L1 | Low | `str.lower()` is not a canonical Unicode fold; NFC/NFD and full-case-map spellings stay distinct, splitting a tag and defeating the plain GIN index. | **Accepted** | Normalize with `unicodedata.normalize("NFC", …)` + `str.casefold()`. §3, §12 step 3, §13. |
| L2 | Low | Frontend needs one shared canonicalizer feeding both the query key and params; it must sort **copies** (not mutate React state) and emit repeated params as **tuple pairs** (the object `params` form cannot repeat a key). | **Accepted** | §8 step 4 and §12 step 7 specify a non-mutating sorted-copy canonicalizer and tuple-pair params; verified `api-client.ts:15-17` accepts `[string,string][]`. |

**Verification notes for Finding 1 (why the recommended fix was rejected).** The backend
asymmetry is real — `set_metadata` is grant-aware, so the backend API test still asserts
a granted Viewer *succeeds* (§13). But the recommended UI fix (add `can_edit`, surface the
editor to a granted Viewer) was rejected after reading `agents/[id]/page.tsx:261`: the
**entire** agent Builder — the draft editor, the model panel, the `AvatarColorPicker` (the
very precedent this design copies) and the `SharingPanel` — hangs off one role-level
`const canEdit = can(Perm.agentsEdit)`. A Viewer with a per-agent edit grant already
cannot use *any* of the Builder today; the grant path is an API capability. Surfacing a
categories/tags editor to that Viewer while every other Builder control stayed hidden
would be a **new inconsistency**, not a fix, and out of FA-023's scope. `AgentRead`
carries a per-caller `can_run` (not `can_edit`) precisely because run grants meaningfully
surface per-row controls and edit-in-the-Builder does not. The design gates the metadata
editor on the same `canEdit`, records the decision explicitly, and keeps the "no role →
absent" test rather than the "granted Viewer sees editor" one the finding proposed.

No first-round decision was overturned. Codex also re-confirmed the SQL authorization
composition is tenant-safe: the `&&` predicates only narrow an already org- and
grant-scoped query and cannot widen it.

## 17. Plan review (gpt-5.6-sol)

A third `codex exec` review (`gpt-5.6-sol`, read-only, medium effort) targeted the
**implementation plan** specifically — step sequencing, migration numbering, whether each
settled decision has a concrete step, missing files/steps, and test/coverage
completeness. The run header confirmed `model: gpt-5.6-sol`. Each finding was verified
against the actual code (alembic head, the named files/lines, the coverage config, the
test layers) before a verdict. Codex explicitly **confirmed the migration numbering**:
`0077_drop_allow_byo` is the current head, so `0078_agent_categories_tags` with
`down_revision = "0077_drop_allow_byo"` is valid — matched independently against
`backend/alembic/versions/`.

| # | Sev | Finding | Verdict | Change |
|---|---|---|---|---|
| 1 | High | `normalize_labels_query(values)` cannot apply a per-facet cap (10 vs 20) without knowing the facet; and the strict length check "> 32 after trim" ignores that `casefold()` can *expand* a value past `String(32)`. | **Accepted (both parts)** | Verified: §3 capped "first 10 / first 20" with no facet arg; strict check said "after trim". Gave `normalize_labels_query(values, *, max_items)` (service passes 10/20) and moved the length check onto the **folded** value. §3, §4 filter, §12 steps 3–5. |
| 2 | High | The list page derives empty-state, the Clear-filters CTA and the count from `agents.length`, so a zero-match **server** facet shows "No agents yet" with no way to clear. | **Accepted** | Verified `agents/page.tsx:177` (`agents.length === 0` empty copy, `agents.length > 0` CTA gate, `total={agents.length}`). §12 step 8 now folds the facet into the empty/clear/`total` logic; §13 adds a zero-result facet test. |
| 3 | High | The plan claims the touched platform modules and frontend work are "under the 100% gate"; actually only `agent_registry.py` (backend) is in `include`, and the page files are excluded (frontend). | **Accepted** | Verified against `pyproject.toml` (only `agent_registry.py`; model/schema/repo/route absent) and `vitest.config.ts` (pages excluded). §12 intro and §13 rewritten to state the real gated set and to require full branch coverage of the ungated helpers/predicate anyway. |
| 4 | Med | The named `test_migrations.py` proves only the whole-chain round-trip, not the per-revision defaults/index/preservation the plan asserts. | **Accepted** | Verified `test_migrations.py` has only `upgrade head` / `downgrade base` / cycle / current==head. §7 and §13 now call for a dedicated revision-specific integration test (insert at 0077 → upgrade → assert empty arrays + GIN `amname` → downgrade drops). |
| 5 | Med | Making frontend `Agent.categories/tags` **required** breaks typed fixtures and the backend `_agent` MagicMock. | **Accepted** | Verified the TS `Agent` interface marks listing-filled fields optional and `agent-card.test.tsx` (+ others) build full objects; `_agent` (`test_agent_registry.py:125`) is a bare `MagicMock`. §12 step 7 now declares the TS fields **optional** (matching `channels?`/`shared_user_count?`); step 5 sets `agent.categories/tags = []` on the mock. |
| 6 | Med | Editor/filter controls under-specified (commit/remove/failure behavior; source of filter choices). | **Accepted (scoped)** | Legitimate gaps. §12 step 8 now names the new component files, fixes the interaction (Enter/blur commit, ✕/Backspace remove, pending/failure, render from the normalized response) and declares the facet as free-text tokens (not page-derived), with a managed vocabulary deferred (§15). Did not over-specify beyond that. |
| 7 | Med | Persistence, `&&` semantics, grants and tenant isolation were placed under `tests/api/`, but the api layer runs on a **mocked** DB session. | **Accepted** | Verified `conftest.py` overrides `get_db_session` with `mock_db_session` and `tests/api/*` monkeypatch repos; the rules put real-DB behavior in `tests/integration/`. §13 regrouped: route wiring/422 in api, service authorization/hand-built read in unit, real `&&`/GIN/count/tenant in integration. |
| 8 | Med | The round-trip test names only list/detail/metadata responses, but create/draft/clone/avatar/… also serialize `AgentRead`. | **Accepted (minor)** | Those are `from_attributes` ORM paths that carry the columns for free (§4), so the risk is low; §13 adds a representative create-read-back + avatar-color assertion as a guard rather than exhaustive re-testing. |
| 9 | Low | Route step uses `Annotated` but `agents.py` imports only `Any`; and `list_visible(..., list[str] = [])` is a `B006` mutable-default. | **Accepted (both)** | Verified `agents.py:21` imports only `Any`, and ruff selects bugbear `B`. §12 step 6 adds the `Annotated` import (and notes the FastAPI `Query()` list default idiom); step 4 uses `Sequence[str] = ()`. |
| 10 | Low | i18n step lacks a validation/verification substep. | **Accepted** | §13 frontend now asserts the message-catalog consistency check (en/pl parity) and accessible names on the new controls. |

No design-level decision was overturned; every change above is to the plan's steps and
tests, not to the settled design. The core decision (record metadata over `AgentSpec`),
the strict-vs-query split, required backend `AgentRead` fields, GIN on model + migration,
the `list_visible` filter params, the React Query key shape, and the import/export
contract all stand.
