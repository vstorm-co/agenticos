---
description: Scaffold a new API endpoint with full layering
---

Add an API endpoint: $ARGUMENTS

Read `.claude/rules/architecture.md`, `api-conventions.md` and `schemas-models.md`
first. If the resource is org-scoped or gated, also use the `permissions-rbac` skill —
the gate is the part that breaks silently.

Create in this order:

1. **Schema** (`backend/app/schemas/<entity>.py`) — `BaseSchema` (plus
   `TimestampSchema` for Read); `*Create`, `*Update` (all optional), `*Read`, `*List`;
   `Field()` constraints.

2. **DB model** (`backend/app/db/models/<entity>.py`) — `Base, TimestampMixin`,
   `Mapped[...]` + `mapped_column()`, `__repr__`, `ondelete="CASCADE"`.
   **Org-scoped means `NOT NULL organization_id`** and tenant-scoped unique constraints,
   so a missed `WHERE` is a constraint violation rather than a data leak. Import it in
   `app/db/models/__init__.py`.

3. **Repository** (`backend/app/repositories/<entity>.py`) — stateless async functions,
   keyword-only after `db`, `db.flush()` + `db.refresh()`, **never** `db.commit()`.
   Return the entity, never an id or a dict.

4. **Service** (`backend/app/services/<entity>.py`) — a class taking `db`. Raise
   `NotFoundError` / `AlreadyExistsError` / `AuthorizationError`, never return error
   codes. Thick domain (own clients, adapters, parsers) → a subpackage with a facade;
   see `architecture.md`.

5. **DI** (`backend/app/api/deps.py`) — a factory plus an `Annotated` alias:
   `EntitySvc = Annotated[EntityService, Depends(get_entity_service)]`.

6. **Route** (`backend/app/api/routes/v1/<entity>.py`) — `response_model`, `-> Any`,
   201 on POST, 204 + `response_model=None` on DELETE, `skip`/`limit` on lists.

   **The gate:**
   - Collection routes (`GET ""`, `POST ""`) carry
     `dependencies=[Depends(require(Perm.X))]`.
   - Per-resource routes (`/{id}`, and any action on one row) carry **no** role gate.
     The service calls `resolve_access(...)`. A role gate cannot see a row's grants and
     would refuse a Viewer who holds an explicit grant.
   - Listings need `visible_resource_ids(...)`, or shared rows vanish.
   - Use `Auth` (`AuthContext`) for anything org-scoped. `CurrentUser` /
     `CurrentAppAdmin` are the only user aliases; there is no `CurrentAdmin` or
     `RoleChecker`.

7. **Register** the router in `backend/app/api/routes/v1/__init__.py`.

8. **Migration** — `make db-migrate`, then **review the generated file** and round-trip
   it. Use the `alembic-migration` skill.

9. **Tests** — a unit test per service branch, an API test that the gate refuses the
   wrong caller, and an integration test for any new constraint. Test the refusal and
   test it cross-tenant. Use the `backend-tests` skill; if the module belongs to the
   platform layer, add it to **both** lists in `pyproject.toml`.

10. **Docs** — if this changes behaviour a page describes, update it. See the table in
    `CLAUDE.md`.

11. `make lint && make test-fast`, then `make check` before opening a PR.
