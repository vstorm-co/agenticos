# Permissions

The rule the whole codebase follows: **permissions are defined in code, roles are
composed from them.** Call sites check permissions, never role names, so adding
or re-shaping a role never means editing an endpoint.

The catalog is [`app/core/permissions.py`](reference/permissions.md). It is the
single source of truth; this page explains it.

!!! warning "There are three layers, and they are independent"

    They do not form a hierarchy and none implies another. Most confusion about
    access on this platform comes from assuming otherwise.

    There used to be a fourth - a `users.role` column of `admin` | `user`,
    inherited from the project template, with `User.has_role()`, `RoleChecker`
    and a `CurrentAdmin` alias behind it. It was removed in migration `0066`. It
    was a third answer to a question the two below already answered, and it
    agreed with neither: an account called `admin@example.com` sat at
    `role = 'user'`, which reads as a broken installation and sent people to fix
    the wrong layer.

    It was not quite inert, which is why removing it was a behaviour change:
    `GET /conversations/{id}` and its `/messages` sibling dropped the ownership
    filter for anybody whose `role` said `admin`. Cross-user conversation reads
    now live only on `/admin/conversations`, gated on `is_app_admin`.

## Layer 1: `users.is_app_admin` - the deployment superadmin

A boolean on the user, entirely outside organizations. Two effects:

1. **A gate on deployment routes.** `CurrentAppAdmin` guards `/admin/users`,
   `/admin/stats`, `/admin/conversations`, `/admin/ratings` and the bulk `/rag`
   endpoints.
2. **A bypass in `AuthContext.permissions`**, which returns every permission at
   `Scope.ALL` - in every organization, including ones where they hold no
   membership.

The bypass is deliberate and the docstring says why: such a person administers
the deployment and already has database access, so pretending otherwise would be
security theatre. What holds them to it is the audit log.

```bash
# Grant, or revoke with --revoke.
agenticos cmd create-app-admin someone@example.com
```

`agenticos cmd bootstrap` also grants it to the owner it creates, idempotently.

!!! note "A fresh clone, an old database"

    If `/admin` is refused for the account bootstrap created, the database was
    almost certainly bootstrapped before that grant existed. The column defaults
    to `false` and nothing backfills it. Run `create-app-admin` above.

## Layer 2: the organization role

A row in `organization_members` - one per organization per user - carrying a value
from `OrgRoleName`. This is where the great majority of decisions are made.

Two kinds of permission, and they behave differently.

**Global** permissions are binary and org-wide: `members:manage`, `roles:manage`,
`org:settings`, `org:delete`, `budgets:manage`, `approvals:decide`,
`connections:manage`, `mcp:manage`, `channels:manage`, `runs:view`,
`audit:read`.

**Resource** permissions carry a `Scope`, because they answer the second question
a role cannot: not "may this role touch agents?" but *which* agents.

### Scope

Ordered `NONE < OWN < SHARED < TEAM < ALL`.

| Scope | Reaches |
|---|---|
| `NONE` | nothing |
| `OWN` | rows this person owns |
| `SHARED` | their own, plus anything org-visible |
| `TEAM` | their own, plus team-visible and org-visible |
| `ALL` | every row in the organization |

!!! info "Why the comparison operators are overloaded"

    `Scope` subclasses `str`, so without them Python would compare the values
    alphabetically - `all < none < own`, the opposite of what they mean. Mixed
    comparisons raise `TypeError` rather than returning a silently wrong answer,
    because a wrong answer in an authorization check is worse than a loud one.

`TEAM` is not used by any built-in role today; it exists for custom roles.

### The built-in roles

| Role | Idea | Agents | Secrets | Global |
|---|---|---|---|---|
| `owner` | owns the organization | all `ALL` | `ALL` | everything, including `org:delete` |
| `admin` | runs it day to day | all `ALL` | `ALL` | everything **except** `org:delete` |
| `builder` | builds, and learns from the whole org | `view`/`run` `ALL`, `edit`/`publish` `SHARED` | `view` `SHARED`, `edit` `OWN` | `mcp`, `connections`, `runs:view` |
| `operator` | keeps the running system healthy | `view`/`run` `ALL`, no edit | `view` `SHARED` | `approvals:decide`, `runs:view` |
| `member` | the everyday user | `view`/`run` `SHARED`, `edit` `OWN` | `view` `SHARED`, `edit` `OWN` | none |
| `viewer` | reads | `view` `SHARED` | none | none |

The `builder` / `admin` distinction is the interesting one: a builder sees the
whole organization in order to learn from it, but edits only what is theirs or was
shared with them - so one builder cannot rewrite another's agent.

Roles are not user-editable, and nothing seeds them: there is no roles table. A
role is a string on the membership row, and what it means is `ROLE_PERMS` in
code - so adding a role is an edit there rather than a migration, which is the
point of composing roles from permissions.

The column carries no CHECK constraint, unlike `resource_grants.level`. What
keeps an invented role out is a validator on the member and invitation schemas,
and if one ever got through, an unknown role resolves to no permissions rather
than to somebody else's.

Custom roles are Phase 2 and may only ever recombine the permissions above;
clients cannot invent new ones.

## Layer 3: visibility and grants

Every shareable resource carries an `owner_user_id` and a `visibility`
(`private` | `team` | `org`). On top of that, `resource_grants` holds one row per
share: one resource, one person, one level.

| Level | Allows |
|---|---|
| `read` | see the configuration |
| `use` | also run or attach it |
| `edit` | also change it |

The table is deliberately generic - `resource_type` + `resource_id`, with no
foreign key to the target - because agents, collections, skills and stored keys
all share the same rules. The trade-off is that the database cannot cascade-delete
a grant when its target goes away, so services delete grants alongside the
resource.

## How the layers combine

One formula, in `app/services/access.py`:

```
effective access to one row = max(role scope, grant on that row)
```

**A grant widens what a role allows; it never narrows it.** Sharing one agent
with a Viewer works without promoting them, and a Builder's org-wide view is not
taken away by the absence of a grant.

`resolve_access` in order:

1. No subject in the context → refused. Always, whatever the role says.
2. `resource.organization_id != ctx.organization_id` → refused. **Tenancy is
   checked before anything else.**
3. Does the role's scope alone reach this row? If yes, done - no query.
4. Only now is `resource_grants` consulted, and the level compared against the
   minimum the permission requires.

### Listings

`visible_resource_ids` answers the same question for a list, and has one trap
worth knowing: it returns `None` when the role already reaches everything ("no
filtering needed") and an **empty list** for a context with no subject. Those are
opposites, so confusing them would widen a listing to the whole organization at
exactly the moment it should be narrowed to nothing.

The agents, skills and kb listings also take `?shared_with_me=true`: only rows
deliberately shared with the caller - org-visible or explicitly granted, and
never their own. The narrowing applies whatever the role's scope, which needs
one care: a role that reaches everything never looks its grants up for a plain
listing, so the filter fetches them anyway - without that, a Builder's "shared
with me" would degenerate into "the whole organization minus mine". For kb it
also excludes personal rows (the caller's by construction) and app-scope rows
(the deployment's - never shared *with* anybody).

## Where the gates go

!!! danger "`require(...)` belongs on collection routes, not per-resource ones"

    Listing, creating and reading a catalog carry a role gate. Anything acting on
    *one* agent, skill or collection must not.

    A role gate cannot see the grants on a row, so it would refuse a Viewer
    holding an explicit `edit` grant before `resolve_access` ever widened their
    access - which contradicts "a grant widens what a role allows". Per-resource
    routes hand the decision to a service that calls `resolve_access`.

    `tests/api/test_platform_routes.py` enforces both halves.

There is a third placement, for a route whose *parameter* decides the question.
`GET /stats/usage` and `GET /ratings/summary` serve two askers behind one path:
`scope=org` reads everybody's rows and demands `runs:view`, while `scope=own`
reads only the caller's own and demands nothing beyond a signed-in membership. A
route-level `require(runs:view)` would refuse a member's `scope=own` before the
parameter was ever read, so the route carries no gate and `StatsService` makes
the decision - the same principle as per-resource routes (the layer that can
see the deciding fact decides), where the fact is the scope parameter rather
than a grant on a row. The route sweep recognizes such a service the same way
it recognizes the grant-aware ones, and
`tests/api/test_platform_routes.py::TestStatsScopeIsDecidedInTheService` proves
the refusals.

## Contexts with no subject

`AuthContext.user_id` is optional, and that is a statement rather than a
convenience. Every run on this platform has a subject: budgets, grants, the audit
trail and the approval gate all key on one.

- `AuthContext.anonymous()` is the only constructor for such a context, so "where
  can a subject-less context come from" is a `grep` rather than an audit.
- Its role is the string `"anonymous"`, deliberately not a member of
  `OrgRoleName` and not a key of `ROLE_PERMS`, so it can never pick up
  permissions from a later edit to either.
- `.permissions` returns `{}` when there is no subject - checked on the subject
  rather than on the role string, because a subject-less context built with
  `"owner"` would otherwise reach every row in the organization.
- `.subject_id` raises `AuthorizationError` rather than returning `None`, because
  the audit actor column is `NOT NULL` and letting the absence travel surfaces
  several layers down as an `IntegrityError` - by which point the audit entry is
  lost and the request has half happened.

What such a run is allowed to do comes from the **exposure** that admitted it,
created by somebody who did have a role.

## What the frontend reads

| Endpoint | Answers |
|---|---|
| `GET /me/permissions` | the caller's role, `is_app_admin`, and every permission with its scope |
| `GET /roles/catalog` | the whole catalog and what each role bundles |

Both are **a convenience for the UI and nothing more**. The server re-checks every
permission on the endpoint that performs the action, so a client that ignores
these APIs gains nothing.

## Reference

::: app.core.permissions.Perm

::: app.core.permissions.Scope

::: app.core.permissions.AuthContext
