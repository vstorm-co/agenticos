---
name: alembic-migration
description: Change the PostgreSQL schema with Alembic — add or alter a table, column, index or constraint, backfill data, or tighten a rule on a column that already holds rows. Use whenever a SQLAlchemy model changes, and whenever a validation rule narrows on a field stored as JSON. A model change without a migration passes the unit suite (sessions are mocked) and breaks on real Postgres.
---

# Migrations

Async SQLAlchemy 2.0 + Alembic on PostgreSQL. `backend/alembic/versions/`, numbered
`0001_…` upward. `.claude/rules/schemas-models.md` has the model shapes.

**The chain starts at `0001_baseline`,** which is 65 earlier revisions collapsed into
one on 2026-07-31. Read its docstring before your first migration: it records the
model/migration drift that squash resolved, and why three indexes had to be moved
onto the models first. **The numbering restarted with it**, so a revision number
cited anywhere for work that predates the squash - `0038` for the vault,
`0066` for `users.role`, `0046` for the Tesseract codes - now names a *different*
migration in this directory, or none. That is worse than a dangling reference
because it resolves. Cite a revision by its full file name and only while it is
still here; anything older is in `0001_baseline` and in git history before
2026-07-31.

**The models are the source of truth now, and that is newly true.** Before the
squash they were not: composite indexes and a CHECK existed only in migrations, so
autogenerate emitted four hundred lines of drift on every run and a real change hid
in it. If autogenerate is noisy again, that is the signal something was added to a
migration by hand and never declared on the model — fix the model, do not accept
the noise.

**One family of tables alembic does not own.** The vector store creates
`rag_<collection>` per collection at runtime, so `alembic/env.py` filters them out of
the comparison through `include_name`; without that, `make db-check` failed on any
database that had ever ingested a document, reporting somebody's collections as tables
to drop. Two things follow. Do not add them to the models to quieten a diff — they are
per-tenant runtime objects, and declaring them would have alembic dropping a
collection. And keep the predicate in `app/db/vector_tables.py` narrow: `rag_documents`
*is* a model table, and an exclusion that reached it would silence real drift in the one
table ingestion writes through.

## Workflow

1. **Change the model** in `backend/app/db/models/`. `Mapped[...]` + `mapped_column()`,
   `__repr__`, `ondelete="CASCADE"` on parent references. Import it in
   `app/db/models/__init__.py` or autogenerate will not see it.

2. **Autogenerate:**
   ```bash
   cd backend && uv run alembic revision --autogenerate -m "add <thing>"   # or: make db-migrate
   ```

3. **Review it. Always.** Autogenerate is a draft:
   - `upgrade()` matches the intent and `downgrade()` actually reverses it
   - `down_revision` chains onto the current head (`uv run alembic heads`)
   - no dropped columns or tables you did not intend
   - server defaults, enum changes, JSONB and array types — the usual autogenerate
     blind spots
   - name the file with the next sequential prefix, and give it a **docstring** saying
     why. Read `0042_sync_source_secret_id.py` for the standard - what the
     column is for, what the alternatives were, and why this one was followable.

4. **Apply, then round-trip:**
   ```bash
   uv run alembic upgrade head && uv run alembic current
   uv run alembic downgrade -1 && uv run alembic upgrade head
   uv run pytest tests/test_migrations.py   # the whole chain, forwards and back
   ```
   That module is what proves `downgrade()` is real. It runs in `make test`, against
   a database it creates and drops itself (`agenticos_migrations_test_p<pid>`), so it
   is also safe to run while your own database is populated. `make test-migrations`
   asks the same question by hand — but against whatever `backend/.env` names, which
   on a laptop is the database with your work in it.

## Tightening a rule is a data migration

This is the trap worth internalising, because nothing fails until a user opens a page.

A narrower rule does not only reject new input — **it makes existing rows unreadable**,
and a Pydantic model that refuses to validate one field of one row takes down the whole
listing endpoint with a 500.

The worked example is the one that narrowed `IngestionConfig.ocr_language` from
"anything 2–16 characters" to Tesseract's `^[a-z]{3}(\+[a-z]{3})*$` while every row
written before it held `"en"`. The data migration shipped in the same revision; the
revision itself predates the squash and is inside `0001_baseline`.

- **Adding** a field to a JSONB-stored model is safe — missing keys take their default.
- **Narrowing** an existing one needs the backfill in the same change.

The same applies to the agent spec, which is stored as JSON. See the `agent-spec` skill.

## Multi-tenancy

Org-scoped tables carry a `NOT NULL organization_id` and tenant-scoped unique
constraints — isolation is enforced by the schema so a missed `WHERE` is a constraint
violation rather than a data leak. The pattern for retro-fitting that onto an
existing table is **fill the column, then constrain it, in that order and in one
revision** - `0023_embed_kinds` is the worked example: two `UPDATE`s give every
existing row a `kind` and a `config`, and only then do the two
`alter_column(nullable=False)` calls run.

Where the value cannot be derived, the honest alternative is **refuse**, not
guess. `0042_sync_source_secret_id` does that: it counts the `sync_sources` rows
with a null `organization_id`, raises if any exist with what to do about them,
and constrains the column afterwards. An id invented for a tenant-scoped row is a
row in the wrong tenant.

Anything encrypted needs a `secret_key_version` column — a staged master-key rotation
has to know which key sealed an envelope. See the `vault-secrets` skill.

## Backfills

Explicit `op.execute(...)` or a small data loop in `upgrade()`. Keep schema and data
changes in separate, well-named revisions **unless** the data change is what makes the
schema change safe — then they belong together, as above.

## Rules

- **Never edit a migration already applied in a shared environment.** Add a new one.
- `make dev` / `make platform-bootstrap` run `alembic upgrade head` automatically.
- A model change without a migration **passes the unit suite** — sessions are mocked.
  Only `make test-integration` and `make test-migrations` see it.
- A new constraint deserves an integration test that it actually rejects a row. A mock
  cannot tell you a `CHECK` fires. See the `backend-tests` skill.
