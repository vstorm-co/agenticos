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

One shared, pure helper `normalize_labels(values: list[str]) -> list[str]` in
`app/schemas/agent.py`, reused by the command schema validator and by the list-filter
query normalization in the service. Rules, applied in order:

1. **Trim** each item and collapse internal whitespace runs to a single space.
2. **Lower-case** (canonical fold — see rationale below).
3. **Drop empties** (an item that is empty after trimming disappears — this is how
   "empty values" are handled consistently).
4. **De-duplicate**, preserving first-seen order.
5. **Bound**: each item ≤ 32 chars (enforced by `String(32)` and by the validator so
   the refusal is a clean 422, not a DB error); at most **10 categories** and **20
   tags** (a `Field`/validator cap so a runaway list can't bloat a row or a card).

**Casing decision: fold to lower-case on write.** This makes de-duplication,
filtering and indexing all exact and consistent (`"Sales"` and `"sales"` are one tag,
and a plain GIN index answers the filter). The tradeoff is losing the author's original
capitalization; the UI can present a prettified/title-cased label for display. The
rejected alternative — preserve display casing but match case-insensitively — needs an
expression GIN index over `lower()` of each array element (an immutable array-lowercasing
wrapper), which is materially more complex for a cosmetic gain. Codex is asked to weigh
this explicitly.

Because normalization lives in the schema validator, an unnormalized body (`["Sales",
"sales", "  "]`) is accepted and stored as `["sales"]` — duplicates and empties handled
by construction, and idempotent (re-normalizing changes nothing).

## 4. API surface

### Read

Add to `AgentRead` (`backend/app/schemas/agent.py`):

```python
categories: list[str] = Field(default_factory=list)
tags: list[str] = Field(default_factory=list)
```

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
        return normalize_labels(v)
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

Threaded `list_agents(ctx, ..., categories=..., tags=...)` → `agent_repo.list_visible`,
which adds a `.where(...)` to **both** the data query and the count query:

```python
if categories:
    query = query.where(Agent.categories.op("&&")(normalize_labels(categories)))
    count_query = count_query.where(Agent.categories.op("&&")(normalize_labels(categories)))
if tags:
    query = query.where(Agent.tags.op("&&")(normalize_labels(tags)))
    count_query = count_query.where(Agent.tags.op("&&")(normalize_labels(tags)))
```

Semantics: **overlap (`&&`) within a facet = OR**; **categories AND tags across
facets**. Query values are normalized the same way as stored values (lower-cased), so
matching is case-insensitive by construction. Order/count stay as they are.

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
- Round-trip verified by `tests/test_migrations.py` (forwards/back) and
  `make db-check` (model↔migration parity).

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
4. **Filter**: server-driven facet. Extend `qk.agents.list` and `useAgents` to pass
   `category`/`tag` params; add the facet control to `galleryControls` in
   `agents/page.tsx`. Keep the existing text/status filters as they are. (Text/status
   stay client-side; the tag facet goes to the server so it filters the whole set, not
   just the first page.)
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
- **No agent-record export today includes avatar metadata** (export is spec-only via
  `export_spec` → `spec.to_yaml()`), so there is no other export surface that must learn
  about tags. If a record-level agent backup/export is added later, it should carry
  categories/tags alongside avatar for the same reasons.

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
| 3 | Med | `Field(max_length=10/20)` caps **list length**, not item length; an overlong label would hit `String(32)` as a 500/DB error, not a clean 422. | **`normalize_labels` enforces per-item length itself** (raise `ValueError` → Pydantic 422 for an item > 32 chars, after trim). The list-count cap stays as `max_length` on the field; the two caps are documented as distinct. Filter-side normalization skips/truncates rather than raising (a bad query param should narrow, not 400 the discovery page — decision noted in §4). |
| 4 | Med | Model snippet only adds columns; GIN indexes must also be declared on the model (`__table_args__`), not just the migration, or model-built test schemas miss them and `make db-check` can drift. | **Add `Index("ix_agents_categories", "categories", postgresql_using="gin")` and the tags equivalent to `Agent.__table_args__`**, import `ARRAY`, `Index`. Implementation step 1 spells this out. |
| 5 | Med | `AgentRead` rows in `list_agents` are **constructed by hand** (not `from_attributes`), so adding fields to the schema alone leaves list cards without them. | **Add `categories=agent.categories, tags=agent.tags` to the `AgentRead(...)` construction** in `AgentRegistryService.list_agents`. Called out as its own implementation step. Detail path (`AgentDetail`/`get`) does use `from_attributes` and needs no change beyond the schema field. |
| 6 | Low | Clone copies the draft spec only, not row metadata; users might expect tags to travel with a clone. | **Documented decision: a clone starts untagged**, consistent with avatar metadata (a clone also starts with no avatar). Noted in the docs update and in a clone regression assertion. |

No findings rejected.

## 12. Implementation plan (ordered)

Each step maps to files and notes the coverage/parity gate it must satisfy. Platform
modules touched are under the 100% gate.

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

3. **Normalization helper + schemas** — `backend/app/schemas/agent.py`
   - `normalize_labels(values: list[str]) -> list[str]`: trim + collapse internal
     whitespace, lower-case, drop empties, dedupe (first-seen order), **raise
     `ValueError` on an item > 32 chars after trim** (Codex #3 -> clean 422).
   - `AgentRead`: add `categories: list[str] = Field(default_factory=list)` and
     `tags: list[str] = Field(default_factory=list)`.
   - `AgentMetadataRequest(BaseSchema)`: `categories` (`max_length=10`), `tags`
     (`max_length=20`), each with a `mode="after"` `field_validator` calling
     `normalize_labels`.

4. **Repository** — `backend/app/repositories/agent.py`
   - `list_visible(...)` gains `categories: list[str] = []`, `tags: list[str] = []`
     kw-only params. Apply `Agent.categories.op("&&")(categories)` /
     `Agent.tags.op("&&")(tags)` to **both** `query` and `count_query`, **only when the
     (already-normalized) list is non-empty** (Codex #1). Caller passes normalized lists.

5. **Service** — `backend/app/services/agent_registry.py`
   - `set_metadata(ctx, agent_id, *, categories, tags)` mirroring `set_avatar_color`:
     `self.get(ctx, agent_id, perm=Perm.AGENTS_EDIT)` then `agent_repo.update`.
   - `list_agents(...)`: accept `categories`/`tags`, **normalize them once** via
     `normalize_labels` (empty stays empty), pass to `list_visible`.
   - Add `categories=agent.categories, tags=agent.tags` to the hand-built `AgentRead(...)`
     (Codex #5).
   - (Clone unchanged — starts untagged, Codex #6; assert in tests.)

6. **Routes** — `backend/app/api/routes/v1/agents.py`
   - `PATCH /agents/{id}/metadata` -> `set_agent_metadata` (no route gate), body
     `AgentMetadataRequest`, `response_model=AgentRead`.
   - `GET /agents`: add `category: Annotated[list[str], Query()] = []` and
     `tag: ... = []`; thread into `service.list_agents`.

7. **Frontend types + hook + query key**
   - `src/types/agents.ts`: add `categories: string[]`, `tags: string[]` to `Agent`.
   - `src/lib/query-keys.ts`: `agents.list(includeArchived, categories=[], tags=[])`
     keyed on sorted facet arrays (Codex #2).
   - `src/hooks/use-agents.ts`: `useAgents` accepts the facet, threads it into the key
     and the `GET /agents` params (`category`, `tag` repeated); `useAgent` gains a
     `setMetadata` mutation -> `PATCH /agents/{id}/metadata`, invalidating `qk.agents.all()`.

8. **Frontend UI**
   - Chips-input editor component under `src/components/agents/` (built on `Input` +
     `badge`), gated on `can(Perm.agentsEdit)` (not rendered otherwise); placed in the
     detail page beside the avatar controls; autosaves via `setMetadata`.
   - Category/tag chips on the agent card + detail header for display.
   - Facet control added to `galleryControls` in `agents/page.tsx`, driving the
     server-side params.

9. **i18n** — `frontend/messages/en.json`
   - Editor + filter labels under `pages.agents`; a create-form label under `agents`
     only if create-time tagging is added (deferred by default). `pl.json` only if
     translated (en merged as fallback).

10. **Docs** — see §14.

## 13. Test plan

Backend (anyio; 100% gate on platform modules — every new line/branch covered):

- **Unit — `normalize_labels`**: trims, collapses whitespace, lower-cases, drops empties,
  dedupes preserving order, is idempotent, and **raises on an over-length item** (-> 422
  through the schema).
- **Schema** — `AgentMetadataRequest` normalizes `["Sales","sales","  "]` -> `["sales"]`;
  count caps (11 categories / 21 tags) rejected; `AgentRead` carries the fields.
- **API — edit** (`tests/api/`): `PATCH /agents/{id}/metadata` sets, changes and clears
  (empty list) both facets; persists across a re-fetch; duplicate/empty/mixed-case input
  stored normalized. **Refusal**: a caller without `agents:edit` is refused; a Viewer
  **with an `edit` grant** on that agent succeeds (grant widens, not promotes);
  **cross-tenant** PATCH is a 404 even when the caller owns a same-named agent elsewhere.
- **API — filter/discovery**: `GET /agents?tag=x` returns only matching visible agents;
  `?category=a&tag=b` ANDs across facets, multiple `tag` ORs within the facet;
  case-insensitive match; `?tag=%20` (blank) is a no-op that returns the full visible
  list (Codex #1 regression); `total` reflects the filtered count.
- **Tenant isolation on filter**: an agent in org B carrying tag `x` never appears in
  org A's `?tag=x`; a private/ungranted agent in the caller's own org carrying `x` does
  not appear for a caller who cannot see it (filter narrows the visible set only).
- **Clone**: cloning a tagged agent yields an untagged clone (Codex #6).
- **Route-gate contract**: `tests/api/test_platform_routes.py` — the new per-resource
  PATCH carries **no** `require(...)` gate; the collection `GET` keeps its
  `AGENTS_VIEW` gate.
- **Migration/integration** (`test-integration` / `test_migrations.py`): columns exist
  with empty-array default on a pre-existing row; GIN indexes present; up/down round-trip;
  `make db-check` clean.
- **Coverage-gate contract**: if any new module is added to the platform layer, keep
  `[tool.coverage.run] include` and `[[tool.ty.overrides]] include` aligned
  (`test_coverage_gate.py`). (No new module expected — changes land in existing covered
  files.)

Frontend (`*.integration.test.tsx`, Testing Library vs. mocked API; 100% gate):

- Editor control **absent** without `agents:edit`, **present** with it (not
  rendered-then-403).
- Editing submits normalized categories/tags to `PATCH /agents/{id}/metadata` and shows
  the resulting chips.
- The facet control drives the request params and the query key changes with the facet
  (no stale cache, Codex #2); the filtered list renders only matching cards.
- Assert on **data**, not chrome (empty-state trap).

## 14. Documentation

- `docs/concepts.md` — note categories/tags as mutable, org-local agent metadata
  (contrast the versioned spec), and that they are **not** part of the exported spec (so
  a clone/export starts untagged), mirroring the avatar wording.
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
