---
description: Review code changes against project conventions
---

Review the staged and unstaged changes on this branch.

Read the change in the context of the system, not as a diff. For each file, check:

**Authorization** — the half that breaks silently
- `require(...)` on collection routes only. A per-resource route with a role gate
  refuses a Viewer holding an explicit grant, before `resolve_access` can widen it
- Per-resource decisions in the service, via `resolve_access(...)`
- Listings call `visible_resource_ids(...)` — `None` means "reaches everything", `[]`
  means "nothing extra"; confusing them leaks or hides rows
- No `UserRole`, `has_role`, `RoleChecker`, `CurrentAdmin`, `CurrentSuperuser`, no
  `--role` flag. Those were removed in migration `0066`
- Org-scoped rows: is the tenant actually constrained, in the schema and not only in a
  `WHERE`?

**Architecture**
- Routes call services, never repositories
- Services raise domain exceptions, never HTTPException
- Repositories: `db.flush()` + `db.refresh()`, **never** `db.commit()`
- `Annotated` aliases from `deps.py`, not raw `Depends()` in signatures
- Route return type `-> Any`, `response_model` does the serialization

**Secrets**
- Everything at rest goes through `app/core/vault.py`. A second encryption mechanism is
  the defect migration `0038` removed
- No plaintext in a response, a log line, an audit entry or a spec. `SecretStr` on every
  secret-bearing field
- A capability declares a secret *kind*; a binding names the instance

**Agent changes**
- A new tool declared in `@register(tools=...)`, or it cannot be gated or renamed
- The capability module in `load_builtins()`
- A capability `id` unchanged
- A spec field change: does an **old stored document** still load? Narrowing a rule on a
  JSON-stored field needs a data migration in the same change

**Types and style**
- Full hints; no `Any` escape hatch, no `# type: ignore` / `ty: ignore` without a
  comment saying what holds it true
- `str | None`, not `Optional[str]`; `datetime.now(UTC)`; `secrets.compare_digest`
- Imports ordered stdlib → third-party → local
- No debug code, commented-out code, or a TODO with no issue

**Tests**
- Does a new behaviour have a test that would fail without it?
- Is the **refusal** covered, and cross-tenant?
- Right layer: a constraint needs `tests/integration/`, a route gate needs `tests/api/`
- Platform-layer module added to **both** lists in `pyproject.toml`
- No test that passes with the implementation deleted

**Docs** — behaviour changed means the page changed, in this change. Run
`python3 scripts/docs_drift.py`; it names the pages owed. A refactor with no
behaviour change owes nothing — say so rather than editing a page for the sake of
it. The trigger map is in `CLAUDE.md` under *Documentation*.

Then run:

```bash
make lint
make test-fast     # or make test if the platform layer changed
```

Report findings with `file:line` references, most severe first, each with the concrete
failure it causes. Say plainly if you found nothing worth changing.
