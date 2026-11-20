# Claude subscription runtime

This optional private service connects a person's Claude account to existing
T3OS agents. The UI follows the link-and-paste pattern used by OpenBot: the
official client starts `claude auth login --claudeai`, the user completes the
provider's page, and the returned code goes to that same waiting process.
The application presents ordinary connection controls and model selection.

The runtime uses the unmodified `@anthropic-ai/claude-code` **2.1.319** package.
It runs inference through the official [programmatic CLI interface](https://code.claude.com/docs/en/headless),
with structured output and native tools disabled. T3OS converts the resulting
tool decisions into real Pydantic AI tool calls. The existing application loop
executes those tools, handles approvals and supplies their results on the next
step. The runtime never reads or exports the CLI's credential files.

## Enable the service

Deploy [compose.yaml](compose.yaml) on the API's private Docker network. Supply
the runtime's key through protected deployment settings, and keep the persistent
state volume. No public port, hostname or WebSocket route is needed.

| Setting | Where | Purpose |
| --- | --- | --- |
| `CLAUDE_SUBSCRIPTION_SERVICE_KEY` | Runtime, API and worker | Same independently generated random value, at least 32 ASCII characters. |
| `CLAUDE_SUBSCRIPTION_URL` | API and worker | Private service address, for example `http://claude-subscription:8080`. |
| `CLAUDE_SUBSCRIPTION_BLOCKED_CIDRS` | Runtime | Comma-separated VM public IPv4 addresses/ranges that native users must not reach. Private, link-local and loopback ranges are also blocked. |
| `AGENTICOS_NETWORK` | Compose | Existing private Docker network shared with the API. |

Deploy matching API, worker and frontend code. Migration
`0296_personal_model_connections` must already be applied; this addition needs no
further schema migration. Check private `/health`, then open
**Settings → AI connections → Claude subscription**. An unconfigured deployment
shows that the runtime is unavailable rather than presenting a working login.

This compose is an optional service definition, not an instruction to replace
the current demo's database, cache or other Coolify services. Build and verify
the new images, inspect the current deployment and preserve its unrelated
configuration when promoting a release.

## Account and process boundaries

Every `(organization_id, user_id)` receives a permanent operating-system UID and
a private `0700` home. The root-owned registry never recycles UIDs. Login,
status, inference and logout all use that same native environment. Only the API
can select an owner; its authenticated context and immutable model ownership
are checked before the runtime is called.

The subprocess environment is an explicit allowlist. It carries no application
service key, organization API key, OAuth-token override or SDK entrypoint
override. Native users can reach public HTTPS and DNS, with private networks,
the VM's own public addresses and other ports denied. Native subprocesses drop
their privileges and supplemental groups and inherit restrictive resource
limits and a `0077` umask.

There is one active native operation per owner and at most four across the
service. Login attempts expire after ten minutes; an unresponsive initial
prompt expires after thirty seconds. A pending attempt has an opaque ID, so
another owner or an obsolete page cannot submit or cancel it. Codes, provider
authorization URLs and raw CLI output never enter application logs or traces.

The native client owns authentication and refresh. Status is checked at first
use and after sign-in, then cached; it does not run concurrently with inference
or continually refresh the account. A disconnected or refused account needs
the user's attention. Disconnect invokes native logout. Disconnect before
deprovisioning a user, and protect the persistent volume and its backups as
credential-bearing data; deleting an application user alone does not erase the
native volume.

## Inference behavior

- The selected model is the native `sonnet`, `opus` or `haiku` alias. The CLI
  resolves the version and reports the actual model and token usage.
- Each native request produces one structured T3OS decision. No filesystem,
  shell, browser, MCP, plugin or hook action is exposed to that model request.
- The full conversation, current instructions and currently available
  application tool schemas go over stdin. Tool results return through T3OS;
  the model cannot authorize or execute an application action itself.
- Text, inline JPEG/PNG/GIF/WebP image bytes and application tools are supported.
  Computer and browser screenshots keep their originating tool-call association
  and reach the native model as image blocks. Image requests use one `stream-json`
  user event and a bounded terminal result; text requests retain the JSON path.
  Image URLs, documents, audio/video and provider-native tools are rejected before
  inference. Responses arrive when the model step completes, using the existing
  chat/tool event stream. Screenshots retain T3OS's ephemeral-history handling.
- The Thinking capability reaches the native CLI as `--effort` and
  `alwaysThinkingEnabled`. `minimal` maps to the CLI's lowest effort, `low`.
  Off requests disable thinking where the model permits it and request low effort
  for models that always think; On preserves the provider's default effort.
  Numeric token budgets and unrelated sampling controls remain unsupported.
- The existing 1 MiB total HTTP request limit includes image base64 expansion,
  conversation and output schema. Oversized requests fail before native work;
  the runtime does not fetch remote images or save screenshot files.
- Stopping the API request cancels the native process. Timeouts and output
  limits also terminate it, including detached processes with that native UID.
- The client uses `--safe-mode`, an empty native-tool list, strict empty MCP
  configuration and no session persistence. It deliberately does not use
  `--bare`, because that mode does not load subscription credentials.

The same personal-connection restrictions apply to direct use, fallback models,
delegates and approval resumes. Another user, an API-key caller, impersonation,
a channel, a workflow or an unattended job cannot spend this account. The
service does not imply provider approval or alter the account's provider terms.

## Verification

Run the focused runtime tests from this directory with the backend's installed
Python environment:

```sh
../../backend/.venv/bin/python -m pytest -q
```

The fake CLI tests exercise real subprocess pipes and the link/code flow,
cross-owner and stale-attempt refusals, cancellation, output limits, credential
environment isolation, structured usage, private RPC authentication and HTTP
disconnect cleanup. They make no provider login or inference request. The
unprivileged test runner checks the requested production UID/GID spawn options
but executes the fake CLI as its own user; production OS and network isolation
also need the container smoke checks before deployment.

Run the focused backend adapter/profile tests and frontend connection tests as
well. Include an application tool → real tool result → final answer and an
approval pause/resume in deterministic model tests. A successful fake run is
not evidence that a particular subscription is eligible or has remaining usage.

## Implementation references

The behavior was reviewed against OpenBot commit
[`53ce25cc2be7a087ee86e65302fb21b8d9e478e4`](https://github.com/nightly-labs/openbot/tree/53ce25cc2be7a087ee86e65302fb21b8d9e478e4),
especially `src/backend/provider-drivers.ts`,
`src/backend/agent/cli-code-login.ts` and `src/backend/claude-client.ts`.
This implementation was written independently; OpenBot's noncommercial source
was not copied into the AgenticOS fork. The native client and Node retain their
own packaged licenses; Node's license is also included under `/licenses/node`.

The sign-in URL allowlist accepts the native client’s current
`https://claude.com/cai/oauth/authorize` page and the legacy
`https://claude.ai/oauth/authorize` page as exact host/path pairs. Other
hosts, swapped paths, user information, non-HTTPS ports and fragments are refused.
