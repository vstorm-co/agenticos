# Secrets and the vault

Every provider key, channel bot token, MCP credential and third-party API key in
this platform passes through one module, and there is deliberately no second
mechanism.

That is a decision with history, and it took two rounds to become true. Three
mechanisms used to hold secrets at rest and only one of them bound a ciphertext to
its owner: provider keys went through the vault, channel bot tokens through a
single deployment-wide Fernet key, MCP tokens through another. A Slack token could
be copied out of one organization's row into another's and it decrypted. Migration
`0038` removed those two.

A fourth survived `0038` and outlived the sentence above it by some months:
`app/core/crypto.py`, one deployment-wide Fernet key over the credential fields of
`sync_sources.config` — the Google service account JSON and the AWS key pair a RAG
sync connector authenticates with. It was honest about itself in its own docstring
and it was still a second mechanism, so a reader who believed "there is no second
mechanism" was wrong about one table. What kept it alive was an ordering problem
rather than a disagreement: an envelope is derived from its owner's id, and
`sync_sources.organization_id` was nullable because the CLI created rows without
one. [#707](https://github.com/vstorm-co/agenticos/issues/707) gave
`rag-source-add` an organization, `0042` made the column say so, and
[#937](https://github.com/vstorm-co/agenticos/issues/937) deleted the module.

**A sync source now references a vault secret by id**, the way
`ModelProfile.secret_id` and `CapabilityBindingSpec.secret_id` do, and its `config`
holds only what a connector needs to *find* the documents. Two consequences beyond
the crypto, and they are the ones an operator notices: a credential is added once
and reused by every source that needs it, rather than pasted per source and rotated
in as many places; and it appears on the Vault page like everything else, so "does
this organization hold a Google credential" has an answer.

## Envelope encryption

Each secret is sealed with its own random data key. That data key is sealed with a
key derived from the master key **and the scope that owns the secret** — an
organization, or the member a personal connection belongs to.

Two properties follow, and both are the reason for the shape:

**A ciphertext cannot be moved between owners.** Even with full database access, a
row copied from organization A into organization B fails to unwrap. Tenant
isolation here is cryptographic, not a `WHERE` clause somebody might forget.

**The master key is rotatable.** It never encrypts a payload directly, only data
keys, so rotating it re-wraps one small blob per secret instead of re-encrypting
every value. Each envelope records the `key_version` that sealed it, which is what
makes a staged rotation possible at all.

The vault decides nothing about *who* may read a secret — that is the
[permission layer](permissions.md). It guarantees only that a secret at rest is
unreadable without the master key and unusable outside the scope it was sealed
for.

## Kinds

A secret is not always a string, and forcing every credential into one "API key"
field produces a form somebody fills in correctly and still ends up with a
credential that fails at the first run. So a secret has a **kind**, and the kind
decides which fields exist.

| Kind | Fields |
|---|---|
| `api_key` | One opaque token |
| `azure_openai` | Key, endpoint, pinned API version |
| `aws_credentials` | Access key id, secret access key, region, optional session token |
| `gcp_service_account` | The service account JSON, validated on the way in |
| `github_oauth_app` | A GitHub OAuth App's public client id and its secret |
| `none` | Not a secret — the marker for an endpoint needing no credential |

`aws_credentials` is the clearest case for kinds existing at all: the access key id
is not secret and the secret access key is, and a single field cannot express that.
`gcp_service_account` is validated at paste time because the failure mode of a
malformed one is an authentication error hours later with nothing pointing back at
the paste that caused it.

`none` is what you store for Ollama on localhost. It is a kind rather than an empty
string so the resolver can switch on a total set — and because the vault refuses to
seal an empty value. Only the runtime can hold `none`; nobody can save one, which
is what keeps "a secret with no value" out of the API schema.

## Where they are used

**Model providers.** Named by a [model profile](models.md). Spend is attributed to
the secret the run resolved to, which is how "which key is costing the most" gets
an answer.

**Capabilities.** A capability declares that it needs a credential of a given
*kind* — never an instance. Code says "I need an API key"; a binding's `secret_id`
says which one. See
[the capability catalog](reference/capabilities.md#what-a-binding-may-change).

**MCP connections.** Bearer tokens and OAuth payloads, sealed to the organization
or to the member. See [MCP](mcp.md#authentication).

**Channel bots.** Every credential on the row, sealed to the bot's organization at
one shared `key_version`: the bot token, a Slack app's signing secret and app
token, and the shared secret an inbound webhook is authenticated against —
Telegram's `X-Telegram-Bot-Api-Secret-Token`, a Mattermost outgoing webhook's
token. See [Channels](channels.md).

**Event triggers.** The secret an event trigger's inbound webhook is verified against -
GitHub's HMAC key, or the signing secret a mail or API relay sends - sealed to the organization and
stored inline on the trigger row with the `key_version` that sealed it, the same shape
as a channel bot's signing secret. It is never returned or logged in the clear; the
verification unseals it, compares in constant time, and a delivery that fails is a 403.
See [Concepts](concepts.md#trigger).

**Third-party services.** A small catalog of services an organization may bring its
own key for:

| Service | Used by |
|---|---|
| Tavily | [`web_research`](reference/capabilities.md#web-search) |
| Brave Search | `web_research` |
| Exa | `web_research` |
| Logfire | Per-agent [observability](reference/spec.md#observability) — traces to a project of its own |
| LlamaParse | PDF parsing, billed to the organization's own key |

## What never happens

- **No API response returns a plaintext.** There is no endpoint for it. The service
  that owns organization secrets has two readers that yield one, and neither hands it
  to a caller: the runner's, while it builds an agent, and the model catalog's, which
  spends a bearer token on one outbound request to a provider and returns the model
  names that came back. Nothing outside that service opens a secret — the model
  listing route used to, and that was the layering defect.
- **No log line or audit entry contains one.** Every secret-bearing field is a
  Pydantic `SecretStr`, so the dataclasses carrying credentials mask themselves in
  a repr — which is the way a plaintext key usually escapes.
- **No spec carries one.** An exported agent spec references secrets by id. That is
  what makes it safe to commit to a client's git repository.
- **A capability never learns where its credential came from**, and the model never
  sees it at all.

Those four are pinned by tests, not by convention.

## Access

| Permission | Grants |
|---|---|
| `secrets:view` | See that a secret exists, its kind, its label |
| `secrets:edit` | Create, rotate, delete |
| `mcp:manage` | Organization MCP connections and their credentials |
| `connections:manage` | Org-wide credentials: model provider connections and sync-source integrations |

Scopes differ by role — an Owner edits any secret in the organization, a Member
edits only their own. A secret can also be shared to a specific member or agent
with a resource grant, which widens access to that one row without promoting
anybody. See [Permissions](permissions.md).

## Operations

The master key is `VAULT_MASTER_KEY`. It falls back to `SECRET_KEY` so a fresh
checkout runs with no extra setup, and an environment validator refuses the default
`SECRET_KEY` outside development — but a production deployment should set it
explicitly.

Losing it means every stored credential is unrecoverable and has to be re-entered.
Rotating it is a staged operation, which the `key_version` column exists to make
possible: `rewrap` moves an envelope to a new version without touching the payload.

```bash
uv run agenticos cmd doctor    # reports whether a vault key is configured at all
```

`make platform-bootstrap BOOTSTRAP_API_KEY=sk-...` stores the first provider key
for you. See [Configuration](configuration.md) for the environment, and
the [production checklist](configuration.md#production-checklist) before going live
with a generated default.
