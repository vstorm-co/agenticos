---
name: native-integration
description: Add or extend a native SaaS product integration shared by capabilities, workflow operations, connected accounts, knowledge sources or watches. Use for provider API operations and account OAuth; use mcp-connections for a remote MCP server instead.
---

# Native product integrations

Read `docs/integrations.md`, then the capability, credential and authorization skills
only for the surfaces the request changes. Inspect a nearby product before adding
another provider. This skill describes platform code, not an agent's published spec.

## Choose the existing seam

- A working MCP server that covers the requested operation may need only a catalog
  entry. Preview-only servers, an unavailable consent path or licensing requirements
  are reasons to inspect the existing native capability path. Do not invent MCP
  availability or claim a native API bypasses provider verification.
- For an existing native provider, extend `backend/app/services/integrations/catalog.py`
  and its narrow transport rather than writing a second SDK client inside a tool.
- `backend/app/agents/capabilities/_integration.py` shares account selection and
  missing-access guidance. Native product packages such as `gmail/` declare their
  registered tool contract. Use the `agent-capability` skill for this surface.
- `backend/app/workflows/nodes/integration_action/` derives workflow operations from
  the product catalog. A new operation normally needs no hand-written parallel node.
- Knowledge ingestion, feeds and watches are separate supported contracts, not
  automatic consequences of adding a tool. Read `files.py`, `feeds.py`, the nearby
  provider's feed module and the `rag-knowledge` / `background-task` skills only when
  those surfaces are requested.

## Account authority is part of the feature

Preserve personal and organization ownership, several simultaneous accounts, the
requesting person's identity and exact approved source accounts. Never substitute
an agent publisher, a different conversation participant or an arbitrary first
account. Ambiguous account choice must be resolved with the person, not guessed.

OAuth may use an organization's Vault app or `OAUTH_BRIDGE_URL` for supported managed
providers. Bridge code lives in the sibling `agenticos-bridge` repository; its
server app secrets never belong in AgenticOS. Tokens, PKCE state and refresh
receipts seal through the existing owner-bound Vault. Reconnect preserves the
account's source; origin changes cannot forward existing tokens elsewhere.

Use `McpConnectionService` and `IntegrationService`, including their live source and
membership checks. Keep the independent refresh transaction and owner lock:
rotating refresh credentials must commit together before another run uses them.
Do not make a library silently refresh an account outside this lifecycle.

## Provider contract

Verify official API and OAuth documentation before declaring scopes or endpoint
behavior. Code owns hosts, methods, path placeholders and query/body allowlists.
Validate identifiers and pagination; do not turn an account into an arbitrary URL
proxy. Mark writes accurately, keep the local write opt-in and return only granted
scopes. Neither a read tool nor a missing approval marker may perform a write.

Missing, revoked or insufficient access gives the agent a useful setup outcome:
name the missing product/account and route the person to Chat preferences, Profile
or organization Vault. Do not silently skip the integration or claim permission
was granted. Temporary provider failure is different from revoked authorization.

## Evidence and completion

Choose the closest files among `backend/tests/test_connected_accounts.py`,
`test_native_boundaries.py`, `test_mcp_refresh_lifecycle.py` and the provider/operation
suite. Test tenant and user isolation, multi-account ambiguity, scope/write refusal,
provider errors, pagination, reconnect and rotated-token persistence. Include real
DB coverage when changing persistence or locking; mocked HTTP does not prove a
real consent or app approval. Update `docs/integrations.md`, capability references
and affected translations. Use scoped tests and CI; do not run every suite locally.


## Customer-owned GitHub App setup

GitHub trigger apps use `github-app-setup`, a separate manifest flow rather than
native product OAuth. Read `docs/triggers.md` and
`app/services/portals/github_app_manifest.py`. The CLI owns the one-time loopback
listener; generated app credentials go straight to the selected organization Vault
through its authenticated API. No bridge or app-secret file is involved. Preserve
read-only selected-event permissions, state validation, credential-free errors,
redirect refusal and the existing app preflight. Do not log the conversion code:
GitHub's conversion endpoint puts it in the URL path. Installation/portal binding
is a subsequent explicit step, not inferred from credential storage.
