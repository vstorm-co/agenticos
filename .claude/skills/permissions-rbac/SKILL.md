---
name: permissions-rbac
description: Gate a route or a service on who may do it — add a permission, wire a role, decide between require() and resolve_access, share a resource with a grant, or debug "this user can see something they should not" and "a Viewer with an edit grant is being refused". Use for any authorization work, any new org-scoped route, and any review of one. There is no UserRole, RoleChecker or CurrentAdmin in this project.
---

# Permissions — three layers, and one rule people get wrong

**Read `docs/permissions.md`** for the model and `docs/reference/permissions.md`
for the generated catalog. `.claude/rules/exceptions-security.md` has the code
shapes. This file is what to do and what not to.

Permissions are defined in code; roles are composed from them. **Call sites check
permissions, never role names**, so adding or re-shaping a role never means
editing an endpoint.

## The rule that gets broken

> `require(...)` gates belong on **collection** routes, not per-resource ones.

| Route shape | Gate |
|---|---|
| `GET /agents`, `POST /agents`, `GET /agents/capabilities` | `dependencies=[Depends(require(Perm.AGENTS_EDIT))]` |
| `GET/PATCH/DELETE /agents/{id}`, `POST /agents/{id}/publish` | **No route gate.** The service calls `resolve_access` |

A role gate cannot see the grants on a row. Put one on a per-resource route and it
refuses a Viewer holding an explicit `edit` grant *before* `resolve_access` ever
widens their access — which directly contradicts the platform's own promise that a
grant widens what a role allows and never narrows it.

`tests/api/test_platform_routes.py` enforces both halves. If it fails after you
added a gate, the gate is the bug.

## The two calls

```python
# Collection route — a permission, as a route dependency.
@router.post("", dependencies=[Depends(require(Perm.AGENTS_EDIT))])
async def create_agent(ctx: Auth, service: AgentSvc) -> Any: ...

# One row — in the service, never as a route gate.
if not await resolve_access(self.db, ctx, agent, Perm.AGENTS_EDIT, resource_type=AGENT):
    raise AuthorizationError(message="...")
```

Listings need the third call, or shared rows silently vanish:

```python
extra = await visible_resource_ids(db, ctx, resource_type=AGENT, perm=Perm.AGENTS_VIEW)
# None means the role already reaches everything — skip the grant lookup.
# An empty list is NOT the same as None; a context with no subject gets [].
```

## The three layers

1. **`users.is_app_admin`** — the deployment superadmin. `CurrentAppAdmin`.
   `uv run agenticos cmd create-app-admin <email> [--revoke]`.
2. **The organization role** — `owner`, `admin`, `builder`, `operator`, `member`,
   `viewer`. Composed from permissions in `app/core/permissions.py`.
3. **Visibility and grants** — a grant on one row. `effective = max(role scope,
   grant on this resource)`.

Capability **scopes** (`knowledge:read`, `web:read`, `code:execute`) are a separate
axis, not a fourth layer: they are what an *organization* allows its agents to do,
checked when an agent is assembled rather than per request. See the
`agent-capability` skill.

Resource permissions carry a `Scope`: `none`, `own`, `shared`, `all`. It answers the
question a role cannot — not "may this role touch agents?" but *which* agents.

## What does not exist

`UserRole`, `User.has_role()`, `RoleChecker`, `CurrentAdmin`, `CurrentSuperuser`.
The `users.role` column was dropped before the migration chain was squashed, so
it lives in `0001_baseline`. Do not reintroduce any of
them, and do not add `--role` to a CLI command. Authority inside an organization is
a membership row plus this catalog.

Only two user aliases exist: `CurrentUser` and `CurrentAppAdmin`. Anything
org-scoped goes through `Auth` (`AuthContext`) plus a permission.

## Adding a permission

1. Add to `Perm` in `app/core/permissions.py`.
2. Add it to every role in the matrix that should have it — with a `Scope` if it is a
   resource permission.
3. Gate the collection routes; hand per-resource decisions to a service.
4. Test the **refusal**, and test it cross-tenant. Most of this platform's value is
   in what it refuses.
5. The frontend reads the effective permission set — check what it hides, and add an
   integration test that a button is actually gone (see the `frontend-feature` and
   `e2e-tests` skills).

## Always test

- **Tenant isolation** — unreachable from another organization *including when the
  caller owns the row*.
- **A grant widening, not promoting** — a Viewer with an `edit` grant on one agent
  edits that agent and nothing else.
- **A context with no subject** — API key, embed session, channel run. See
  `docs/permissions.md#contexts-with-no-subject`.

## Depth

`references/catalog.md` — the permission list, the role matrix, and how
`resolve_access` decides.
