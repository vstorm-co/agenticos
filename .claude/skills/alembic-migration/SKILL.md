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
onto the models first. Revisions the docs cite by number (`0038` for the vault,
`0066` for `users.role`, `0046` for the Tesseract codes) resolve in git history
before that commit, not in this directory.

**The models are the source of truth now, and that is newly true.** Before the
squash they were not: composite indexes and a CHECK existed only in migrations, so
autogenerate emitted four hundred lines of drift on every run and a real change hid
in it. If autogenerate is noisy again, that is the signal something was added to a
migration by hand and never declared on the model — fix the model, do not accept
the noise.

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
     why. Read `0038_one_vault_for_every_secret.py` for the standard.

4. **Apply, then round-trip:**
   ```bash
   uv run alembic upgrade head && uv run alembic current
   uv run alembic downgrade -1 && uv run alembic upgrade head
   make test-migrations   # the whole chain, forwards and back, against Postgres
   ```
   `make test-migrations` is the only thing that proves `downgrade()` is real.

## Tightening a rule is a data migration

This is the trap worth internalising, because nothing fails until a user opens a page.

A narrower rule does not only reject new input — **it makes existing rows unreadable**,
and a Pydantic model that refuses to validate one field of one row takes down the whole
listing endpoint with a 500.

`0046_ocr_language_tesseract_codes.py` is the worked example: `IngestionConfig.ocr_language`
went from "anything 2–16 characters" to Tesseract's `^[a-z]{3}(\+[a-z]{3})*$`, and every
row written before it held `"en"`. The data migration shipped in the same revision.

- **Adding** a field to a JSONB-stored model is safe — missing keys take their default.
- **Narrowing** an existing one needs the backfill in the same change.

The same applies to the agent spec, which is stored as JSON. See the `agent-spec` skill.

## Multi-tenancy

Org-scoped tables carry a `NOT NULL organization_id` and tenant-scoped unique
constraints — isolation is enforced by the schema so a missed `WHERE` is a constraint
violation rather than a data leak. `0027_enforce_org_scope` and
`0029_conversation_org_not_null` are the pattern for retro-fitting that onto an existing
table: backfill, then constrain, in that order, in one revision.

Anything encrypted needs a `secret_key_version` column — a staged master-key rotation
has to know which key sealed an envelope (`0038`). See the `vault-secrets` skill.

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
