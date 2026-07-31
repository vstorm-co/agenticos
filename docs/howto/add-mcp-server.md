# Add a server to the MCP catalog

The [catalog](../mcp.md#the-catalog) is what makes the connection picker useful
instead of a blank URL field. Adding an entry is data, not code: one object in
`backend/app/core/catalog/mcp_servers.json`.

**You do not need to do this to use a server.** Any MCP server reachable by URL
connects through the *Custom server* entry and its tools are introspected on
connect. The catalog saves somebody a URL lookup and a paragraph of setup
guesswork; it is not a gate.

## The entry

```json
{
  "key": "acme",
  "name": "Acme",
  "description": "Read and update work orders.",
  "category": "operations",
  "auth": "token",
  "url": "https://mcp.acme.com/mcp",
  "docs_url": "https://docs.acme.com/mcp",
  "token_hint": "A read-only service token from Settings → API, scoped to work orders.",
  "icon": "acme"
}
```

| Field | |
|---|---|
| `key` | Stable id. Connections record it, so treat it the way capability ids are treated: rename freely, re-key never |
| `name` | What the picker shows |
| `description` | One sentence, in the imperative, about what the *tools* do |
| `category` | Groups the picker. Reuse an existing one unless the server genuinely has no home |
| `auth` | `none`, `token` or `oauth` |
| `url` | Empty when the client hosts the server or the vendor issues a per-account endpoint — the form then asks for it |
| `docs_url` | Where the vendor documents their server |
| `token_hint` | Only for `token`. See below |
| `icon` | A `BrandIcon` name, or empty |

The file is validated against `CatalogEntry` at **import time**, so a malformed
entry refuses to start the app rather than silently vanishing from the picker.

## Write the token hint

This is the field that earns the entry. Generic instructions are the main reason
token setup fails, and "an API token" tells nobody where to click.

Say where the token comes from and what it needs to be able to do:

> A fine-grained personal access token with read access to the repositories the
> agent should see.

Leave it empty for `oauth` and `none` — there is nothing to paste.

## Icons

`icon` names a brand mark. If no compiled-in icon set carries it, drop an SVG at
`backend/app/core/catalog/icons/<name>.svg` and it is served by
`GET /catalog/icons` and drawn for any catalog entry or provider whose id matches.

The file's own colours are **ignored** — it is rendered as a `currentColor`
silhouette, so the console's monochrome register holds by construction. See
`icons/README.md` for the contract.

An empty `icon` falls back to a monogram. That is a deliberate look rather than a
missing one: every icon set is finite and this catalog is not.

## Before you commit it

An entry is a promise — that somebody looked at the server, that the auth flow
works, that the description is honest. That is the whole reason this is a
hand-maintained list rather than a mirror of the public registry, so make the
promise true:

1. Connect it in a running deployment.
2. Run `POST /api/v1/mcp-connections/{id}/test` (the **Test** button) and read the
   tool list it comes back with. If the tools do not match your `description`,
   fix the description.
3. For `oauth`, complete the flow end to end. Discovery, dynamic registration and
   the token exchange each fail differently, and a server that stalls at step two
   looks identical in the UI to one that is merely slow.
4. Check the name does not collide with an existing entry's
   [tool prefix](../mcp.md#name-collisions).

## What does not need changing

Nothing else. The picker renders from the catalog, and the connection service,
probe, allowlist and prefixing are all generic. An entry added here is in the
product on the next restart.
