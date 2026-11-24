# Custom integrations

Build integrations against AgenticOS's supported extension interfaces and the
connected application's own APIs. Keep the platform diff small so upstream
security fixes and improvements remain practical to adopt.

This directory contains extension guidance, the selected
[upstream baseline](upstream.json), deployment instructions for the native
[Composio app connection journey](composio/README.md), the
[per-deployment OAuth runbook](oauth-per-deployment.md) for the native
Google/Microsoft tools arriving with the upstream sync, and the
[Docker image retention operator helper](docker-image-retention/README.md).
The helper is separate from application integrations; no adapter implementation
or runtime compatibility result is claimed.

## Choose the extension interface

| Requirement | Preferred implementation |
| --- | --- |
| An existing supported document source, such as Google Drive | Configure the built-in connector with scoped credentials and an appropriate knowledge collection. |
| New business-system read tools or reviewed actions | A separately deployed, authenticated MCP adapter calling the existing application APIs. |
| An application invoking a published agent | The documented AgenticOS public HTTP API with an explicitly scoped identity. |
| A missing platform guarantee or extension point | A focused platform change with tests, prepared for upstream contribution where useful. |

An MCP service can be connected by URL without adding a catalog entry. Use a
transport supported by the pinned AgenticOS version and retain explicit tool
allowlists. Consult the upstream [MCP guide](../docs/mcp.md) and
[HTTP API contract](../docs/api.md) rather than duplicating their protocols here.

## Public code and private deployments

Reusable adapters and synthetic tests may live in this public fork. Client-specific
adapters and confidential rules belong in private repositories. Use a separate
deployment and credential set for each client, with secrets supplied at runtime
through approved secret storage and AgenticOS vault references where applicable.

Examples must contain synthetic records and placeholder configuration. Exclude
real exports, account identifiers, service-account JSON keys, access tokens,
customer documents and production connection settings.

For document sync, verify the knowledge collection's audience: imported material
uses collection permissions, not the original source's per-document sharing
rules. Scope the source credential to the intended audience as well as selecting
the intended folder. See [file processing](../docs/file-processing.md).

## Initial adapter contract

Start with a small set of read operations, such as an operations-readiness report,
a migration-status report, or a permitted record lookup. These are proposed use
cases, not tools implemented by this baseline.

- Validate typed inputs, bound result sizes and paginate large lists.
- Derive the actor and company scope from verified credentials. Never trust an
  actor or tenant supplied only in the model's prompt.
- Enforce the application's record and field permissions on every request. An
  unrestricted administrator key does not preserve an end user's access.
- Call documented domain APIs. Do not expose arbitrary SQL, RPC methods, shell
  execution or database writes as generic tools.
- Return source record identifiers, permitted links, observation timestamps and
  explicit error states. An unavailable report is not an empty successful report.
- Calculate totals, matching and business constraints in deterministic application
  code. The agent may explain the returned evidence.
- Mark read tools accurately and configure the AgenticOS binding deliberately.
  Its `writes` approval policy trusts the MCP server's read-only declaration.

## Adding write operations later

Reuse the connected application's proposal and approval mechanisms. Bind approval
to the exact payload and actor, recheck current permissions and record state at
execution, and make retries idempotent. An AgenticOS approval cannot substitute
for the application's own business validation.

Record a durable outcome and read back the result. Treat an uncertain external
effect as unresolved until reconciled; do not retry a payment, submission or
dispatch merely because the network response was lost. Keep publication,
financial posting and other high-impact actions outside the initial read-only
adapter scope.

## Acceptance before use

Each implemented adapter needs focused contract tests against the selected
AgenticOS and application versions. Include allowed and denied identities,
cross-client refusal, field filtering, bounded output, unavailable dependencies,
stale data and credential revocation. Test duplicate attempts and uncertain
outcomes before enabling writes.

Use synthetic data and a deterministic model provider during development. Record
test commands, actual results, exact revisions and remaining live acceptance
requirements in the integration PR. Upstream compatibility is earned by those
checks, not by a successful merge or an unchanged version prefix.

See the [fork maintenance guide](../T3_FORK.md) for branches, updates and releases.
