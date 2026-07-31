# The catalog, the matrix, and how access resolves

Source of truth: `backend/app/core/permissions.py` (catalog + role matrix) and
`backend/app/services/access.py` (resolution). Regenerate the reader-facing version
with the docs build — `docs/reference/permissions.md` is mkdocstrings over these
docstrings.

## Two kinds of permission

**Global** — binary and org-wide. You may manage members, or you may not.

```
approvals:decide  audit:read       budgets:manage    channels:manage
connections:manage  mcp:manage     members:manage    org:delete
org:settings      roles:manage     runs:view
```

**Resource** — carries a `Scope`, answering *which* rows.

```
agents:view  agents:edit  agents:publish  agents:run
collections:view  collections:edit
skills:view  skills:edit
secrets:view  secrets:edit
```

`RESOURCE_PERMS` is the set that distinguishes them. A global permission is
`Scope.ALL` for any role that has it at all (`_ALL_GLOBAL`).

## Scopes

| Scope | Reaches |
|---|---|
| `none` | Nothing |
| `own` | Rows this member created |
| `shared` | Own rows plus rows explicitly granted to them |
| `all` | Every row in the organization |

## The role matrix

| | Owner | Admin | Builder | Operator | Member | Viewer |
|---|---|---|---|---|---|---|
| `agents:view` | all | all | all | all | shared | shared |
| `agents:edit` | all | all | shared | — | own | — |
| `agents:publish` | all | all | shared | — | — | — |
| `agents:run` | all | all | all | all | shared | — |
| `collections:view` | all | all | all | all | shared | shared |
| `collections:edit` | all | all | shared | — | own | — |
| `skills:view` | all | all | all | all | shared | shared |
| `skills:edit` | all | all | shared | — | own | — |
| `secrets:view` | all | all | shared | shared | shared | — |
| `secrets:edit` | all | all | own | — | own | — |
| `approvals:decide` | ✓ | ✓ | — | ✓ | — | — |
| `runs:view` | ✓ | ✓ | ✓ | ✓ | — | — |
| `mcp:manage` | ✓ | ✓ | ✓ | — | — | — |
| `connections:manage` | ✓ | ✓ | ✓ | — | — | — |
| other global | ✓ | ✓ except `org:delete` | — | — | — | — |

The reasoning behind each row is in the matrix's own comments. Two worth knowing:

- **Builder** sees the whole org to learn from it but edits only what is theirs or
  was shared, so one builder cannot rewrite another's agent.
- **Operator** keeps the running system healthy — approves, watches, reruns — but
  does not build.

## `resolve_access`

```
effective = max(role scope, grant on this resource)
```

Better of the two, never worse. Sharing one agent with a Viewer works without
promoting them, and a Builder's org-wide view is not taken away by the absence of a
grant.

It checks the role scope first, so the common case costs no query, then falls back to
an explicit grant. **A grant never applies across organizations** — that check is not
optional and is what an integration test should pin.

## `visible_resource_ids`

Returns the extra ids a listing must include *beyond* the scope predicate.

- `None` — the role already reaches everything; skip the grant lookup.
- `[]` — nothing extra. **A context with no subject gets `[]`, never `None`.**

Confusing the two is how an API-key or embed context accidentally sees the whole
organization.

## Contexts with no subject

An API key, an embed session and a channel run have no `user_id`. They cannot hold
grants, so every scope narrower than `all` resolves to nothing for them, and
`visible_resource_ids` returns `[]`. See `docs/permissions.md` for what each surface
is allowed to do instead.
