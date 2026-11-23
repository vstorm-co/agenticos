# Operate AgenticOS with an AI client

The [AgenticOS plugin](https://github.com/vstorm-co/agenticos/tree/main/plugins/agenticos)
adds procedures to the platform MCP tools: choosing a deployment path, configuring
dependencies, building solutions and releasing tested agents. It uses the connected
member's authority in one organization. Installation needs a terminal or CI executor.

## Install and connect

```bash
claude plugin marketplace add vstorm-co/agenticos
claude plugin install agenticos@agenticos
claude mcp add --transport http agenticos https://<api-host>/mcp
```

Finish OAuth in the browser and select the intended organization and scopes.
Settings → MCP clients lists client-specific connection commands. The plugin
contains no fixed server address. See [MCP](../mcp.md) for access and approval rules.

The baseline was tested on 1.82.2. New dependency, quality and bundle tools use
MCP contract 1, advertised by `get_platform_context`. A server without it can
still use its existing tools. The client must discover features and scopes;
version numbers alone do not grant access. Assistant-only routes require OAuth,
while ordinary organization keys retain their public API boundary.

## Build and release a solution

Describe the outcome, users, sources and permitted effects in your own words.
The client discovers capabilities, workflow nodes, connections and existing
resources before designing a solution. Support, repository work and onboarding
bundles are examples, not the limit of supported use cases.

Model profiles can reference existing vault IDs. `list_secret_references` exposes
only accessible names, IDs, kinds and purposes; it omits values and hints.
Embedding endpoint discovery identifies local services. `get_setup_link` hands
credential entry and OAuth consent back to the person's own console session.
Never paste a credential or OAuth callback into the conversation or a bundle.

`plan_solution` validates a manifest and returns its hash and required permissions.
`install_solution` needs that hash, the exact manifest and an installation key.
It creates private resources and its receipt in one database transaction, without
publishing, executing, indexing or scheduling. Matching retries replay the receipt;
a changed manifest on the same caller/organization/key is refused. Another copy
needs another key and resource names that do not conflict.

Logical package references bind agents to their new Context, skills and knowledge.
A workflow preparation can include a table and its placeholder. External model,
embedding and connection references remain explicit deployment-specific IDs.
Read resources back after installation: a receipt is history, not proof they have
not since been edited or removed. Edit installed resources through their normal
operations; installation does not overwrite them as a bundle upgrade.

For a release, create a dataset with scored cases, estimate and run evals, inspect
the result, then publish a version and promote an environment. Pin production
before publishing if it tracks latest and you need staged release. Existing test
connections, guards and override restrictions apply. Roll back by repointing an
environment to an existing version, preserving history. See [Environments](../environments.md).

## Verify a deployment or fork

The deployment skill uses the existing [single-host procedure](../deploy.md),
bootstrap and doctor commands. The development skill maintains a fork's own image
prefix and upstream update PRs. Platform MCP does not grant SSH or cloud authority.

For a disposable local plumbing check from a checkout:

```bash
uv run --directory backend python ../scripts/agenticos_smoke.py --version 1.84.0
# Execute the displayed plan, saving a report outside the disposable stack:
uv run --directory backend python ../scripts/agenticos_smoke.py --version 1.84.0 --run --report /tmp/agenticos-smoke.json
```

The check uses published images, an isolated Compose project, generated local
credentials and a deterministic local model. It bootstraps an organization,
checks the console and API, and completes an agent run through a real MCP client.
It removes its containers and volumes afterwards. This verifies platform plumbing,
not model quality, a paid provider, external DNS or production TLS.
