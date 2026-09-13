# Data protection

Where personal data lives in a deployment, what leaves it and under which
configuration, which controls exist in code with a test behind them, and which
are still open issues. Written for the person answering a data protection
review of one deployment - a DPO, a security officer, an operator - and kept
honest about the difference between what the software can do and what a
deployment has actually decided.

!!! warning "A page is not compliance"

    Nothing here is evidence that a deployment complies with the GDPR. The
    codebase is deployable inside a compliant environment; whether one *is*
    compliant depends on the providers configured, the retention decided, the
    agreements signed and the operator running it. Every such condition is
    named below as something to obtain and verify, never assumed.

## Who is responsible for what

| Party | Role | What that means here |
|---|---|---|
| The organization deploying it (a city, a company) | **Controller** | Decides purposes, retention, which providers an agent may reach, and signs the agreements with them |
| Vstorm, as the software's author | **Neither**, for a self-hosted deployment | The code runs on your infrastructure and nothing phones home. Vstorm never sees your data |
| Vstorm, if it operates the deployment for you | **Processor** | A data processing agreement is a contract between us, not a setting. It has to exist before the first agent is published |
| A model, embedding, parsing, search or observability provider | **Sub-processor**, chosen by configuration | The platform records *which* provider and *which* endpoint each agent uses. Their location, retention and training terms are theirs, and are verified per deployment |

The platform trains and fine-tunes nothing. It sends prompts, documents and
tool results to the providers a deployment configures and stores what comes
back. Whether a provider uses API traffic for training is a property of the
provider's account and terms, and the checklist at the end asks for the
statement rather than assuming it.

## Where personal data lives

Everything below is in the deployment's own PostgreSQL, on its own disk, or in
a service the deployment chose. Every table that holds content carries an
`organization_id`, and every read goes through the access formula in
[Permissions](permissions.md#how-the-layers-combine).

### The database

| Store | Holds | Personal data in it | Purpose |
|---|---|---|---|
| `users`, `sessions`, `organization_members` | Accounts and sign-ins | Email, name, avatar, hashed password or the Google account id, refresh-token hash, IP address and user agent per session | Authentication and authorization |
| `conversations`, `messages`, `tool_calls` | Every chat on every surface | The text people wrote, the model's answers and reasoning, tool arguments and results, a rolling summary of long threads | The product's core function; history the person returns to |
| `chat_files` | Attachments to a message | Filename, type, size, the extracted text (`parsed_content`) and the path of the bytes on disk | Answering about a file |
| `agent_memory_files` | Notes an agent wrote about a person or a group chat | Whatever the agent decided was worth remembering, keyed to `person:<user_id>` or a chat room | Continuity between conversations |
| `rag_documents`, `knowledge_bases` and one vector table per collection | Uploaded and synced documents, their chunks and embeddings | The document text and its vectors, the file's original path in the source | Retrieval |
| `agent_runs`, `tool_approvals`, `run_manifests` | What each run cost and did | The system prompt and last request handed to the model, tool arguments awaiting approval, the deciding person and their note | Budgets, approvals, run history |
| `app_admin_audit_logs` | Who changed access or spent money - the organization trail and the deployment admin's share one table | Actor, impersonator, IP address, the action and a `details` map that names fields rather than values | Accountability. See [Governance](governance.md#audit) |
| `embed_visitors`, `channel_identities`, `channel_sessions` | Strangers on a hosted page and people on Slack, Telegram or Mattermost | A random visitor key; a platform user id, username and display name; the chat id | Resuming the right thread |
| `message_ratings` | Thumbs and comments on answers | The rater and their comment | Quality review |
| `agent_workspaces`, `sandbox_operations` | Files an agent worked on and the log of what it ran | For the `state` backend the files themselves, as JSON; for a container the session id and every command, target and result summary | The sandbox. See [The sandbox](sandbox.md#what-was-done-in-one-and-where-that-record-lives) |
| `organization_secrets`, `model_profiles`, `mcp_connections`, `channel_bots` | Credentials and where they point | Sealed ciphertext only, with a hint; the provider, model and `base_url` in clear | Reaching providers. See [Secrets](secrets.md) |

`messages.search_vector` is a full-text index over the same content, and
`conversations.summary_messages` is a model-written compression of it. Both
are copies of the chat and go with it.

### Outside the database

| Store | Holds | Deleted when |
|---|---|---|
| `MEDIA_DIR` on the API host (`media_data` volume) | Chat attachments, avatars, embed logos, and a temporary copy of each document under `_rag_tmp` while it is parsed | A document is deleted through the product. **Nothing in the product removes a chat attachment's bytes** - not deleting its conversation, not deleting its owner. See [What deletion reaches](#what-deletion-reaches) |
| `SANDBOXD_WORKSPACE_ROOT` on the sandbox host | The files of every container-backed workspace | The conversation is deleted, or `SANDBOXD_WORKSPACE_TTL` sweeps them; unset, they are kept indefinitely. See [How long anything survives](sandbox.md#how-long-anything-survives) |
| Redis | Rate-limit buckets, trigger and channel deduplication keys, OAuth exchange state, staged invitations | On expiry; nothing here outlives its minutes |
| Prefect | Flow-run history and logs | Parameters are ids and paths, never content; the worker's logs pass the same redaction filter as the API's |
| Logfire, when configured | Traces of every run | The provider's retention. Today a trace carries the full prompt, output and tool arguments - see [Traces](#traces) |
| Your SMTP relay | Invitations, magic links, approval requests, budget alerts, usage reports | Whatever the relay keeps. Approval mail names the agent, tool and deciding link, not the tool's arguments |
| Backups | A `pg_dump` is the whole database; the media volume is the files | Your backup expiry. Erasure never reaches a backup already taken - see [Backups](deploy.md#backups) |

## What leaves the deployment

Nothing leaves unless a row or a setting names a destination. This is the
complete list of destinations, with the configuration that decides each.

| Destination | What is sent | Decided by | Location and terms |
|---|---|---|---|
| The chat model | The conversation so far, attachments pasted or described, retrieved chunks, tool results | A [model profile](models.md#a-model-profile): `provider`, `model`, `base_url` and a sealed key. Twenty-seven providers; `ollama` and `litellm` are keyless and reached at an endpoint you host, and `openai`, `anthropic`, `google`, `huggingface` and others accept a `base_url`, so an EU endpoint or a gateway is a field, not a fork | The provider's. Verify per profile |
| The embedding model | Every chunk of every document in a collection, and every retrieval query | `OPENROUTER_API_KEY` deployment-wide, or a per-collection `embedding_provider` and `embedding_secret_id`. The catalog offers OpenRouter and OpenAI | The provider's. [A permanent choice](choosing-models.md#embeddings-are-a-separate-permanent-choice) |
| A cloud document parser | The whole document | `LLAMAPARSE_API_KEY` set **and** a collection's parser set to it. Without the key, parsing is local. `LITEPARSE_OCR_SERVER_URL` names a sidecar you host | LlamaCloud's, if used |
| An image-description model | Images inside documents | A collection's `image_description_model` | That model provider's |
| Web research | The search query the agent composed | A `search` secret for Brave or Exa, bound to the agent | Brave's or Exa's |
| Web fetch and browser use | The URL; for browser use, the whole task | The capability on the spec; browser use also needs a CDP endpoint you name | The site fetched; the browser host |
| An MCP server | Tool arguments and results | `mcp_connections.url`, per organization or per person | The server's operator |
| mem0 | The memories written for a person or a chat | The `memory_mem0` capability's `base_url`, which must be in `MEM0_ALLOWED_HOSTS` | The mem0 host you allow |
| Logfire | Spans for every request and run | `LOGFIRE_TOKEN` deployment-wide; `observability` on a spec redirects one agent's runs to another project. `LOGFIRE_BASE_URL` picks the US or EU deployment | Pydantic's, US or EU |
| Speech to text, image generation | The voice note; the prompt | A profile for `groq`, `mistral` or `openai`; a profile for `google` or `openai` | The provider's |
| Slack, Telegram, Mattermost | The agent's replies | A `channel_bots` row with its token in the vault | The messaging vendor already holds the chat |
| Google sign-in | Nothing outbound; Google returns the email, name, picture and account id | `GOOGLE_CLIENT_ID` | Google's |
| Your SMTP relay | The mail above | `SMTP_HOST`, `SMTP_TLS` | Yours |

Sync connectors run the other way: a Google Drive or S3 source pulls documents
**in**, authenticated by a `connector` secret, and from then on the documents
are the deployment's copy and follow the rules above. The people who can read
what a source ingested is
[a decision the source row makes](file-processing.md#who-ends-up-able-to-read-what-a-source-ingested).

!!! tip "Local models remove most of the table"

    An `ollama` or `litellm` profile, a self-hosted embedding endpoint and local
    parsing leave only the destinations the agent's tools name. [Choosing
    models](choosing-models.md#closed-models-or-open-weights) is the tradeoff.

## Controls, and where each is proved

Each row names the mechanism in code and the test or page that pins it, or
the issue that will. A row whose last column is an issue is a gap, stated as
one.

| Control | Mechanism | Proved by |
|---|---|---|
| Tenant isolation | `organization_id` on every content table; `X-Organization-Id` resolved to a membership on every request | `tests/integration/` tenant-isolation cases; [Permissions](permissions.md) |
| Access to a row | Three layers: deployment admin, organization role, per-resource grant. A control the caller may not use is not rendered | `tests/api/` refusal tests; [Permissions](permissions.md#how-the-layers-combine) |
| Reading another person's chat | Owner, an explicit share, or the deployment's app admin - never an organization role | `admin_conversations.py` requires `is_app_admin`; `ConversationService._may_read` |
| Credentials at rest | Envelope encryption per organization, versioned master keys, rotation with a dry run | [Secrets](secrets.md#what-never-happens), four guarantees pinned by tests |
| Content at rest | **Not encrypted by the application.** Postgres data, `media_data` and the sandbox workspace root rely on disk or volume encryption you provide | Operator control. An S3 backend with server-side encryption for files is [#1423](https://github.com/vstorm-co/agenticos/issues/1423) |
| In transit, inbound | HTTPS at your proxy; `Strict-Transport-Security` when `ENVIRONMENT=production`; session cookies `httpOnly`, and `secure` whenever the request arrived over HTTPS | [Deploy](deploy.md#choose-a-reverse-proxy); `frontend/src/app/api/auth/login/route.ts` |
| In transit, to the stores | `POSTGRES_SSLMODE` and `REDIS_SSL`; `agenticos cmd doctor` reports whether the connection it made was encrypted | [Encrypted connections](configuration.md#encrypted-connections-tls); `tests/integration/test_store_tls.py` |
| In transit, to providers | HTTPS to every catalogued endpoint. A custom `base_url` is refused without a host or with credentials in it, but **`http://` is accepted**, for an Ollama or a gateway on the deployment's own network; a plain-HTTP profile pointing off that network sends prompts and the key in clear. Item 4 of the checklist lists every such profile | `refused_field("base_url", ...)` in the model profile service; operator control for the scheme |
| Secrets in responses, logs, audit, exports | No endpoint returns a plaintext; `SecretStr` everywhere; specs reference secrets by id | [Secrets](secrets.md#what-never-happens) |
| Personal data in logs | `app/core/logging.py` redacts email addresses, JWTs, API keys, bearer tokens and `password=` pairs from every log record, API and worker alike | `tests/test_logging.py`; the worker installs it in `prefect_app.py` (#440) |
| Personal data reaching the model | The `guardrails` capability redacts IBANs, card numbers, US social security numbers and email addresses from prompts, answers and tool results when configured | [Capabilities](reference/capabilities.md); its tests under `tests/` |
| Personal data in a failure column | `rag_documents.error_message` and friends record the stage and class, never the client's text | `app/services/rag/failures.py` (#423) |
| Accountability | Audit entries share the acting transaction and fail closed; impersonation names both people; bulk exports are recorded | [Governance](governance.md#audit) |
| Audit export and tamper evidence | None yet | [#1422](https://github.com/vstorm-co/agenticos/issues/1422) |
| Traces | Full content today, and no switch | [#1413](https://github.com/vstorm-co/agenticos/issues/1413) adds `full`, `redacted`, `none` per agent |
| Retention on a schedule | Only sandbox operation rows (30 days) and stale runs are swept | [#1420](https://github.com/vstorm-co/agenticos/issues/1420) |
| Erasure of one person | Account deletion reconciles what would block it; memory erasure reaches mem0 | [What deletion reaches](#what-deletion-reaches); [#1421](https://github.com/vstorm-co/agenticos/issues/1421) for what it leaves |
| Access to one's own data | No export endpoint; no view of one's own memory | [#1421](https://github.com/vstorm-co/agenticos/issues/1421), [#1594](https://github.com/vstorm-co/agenticos/issues/1594) |
| Enterprise identity | Google sign-in and passwords; no OIDC yet | [#1419](https://github.com/vstorm-co/agenticos/issues/1419) |
| The controls matrix a security review reads | This page and [Rolling it out](rollout.md#what-your-security-review-will-ask) | [#1412](https://github.com/vstorm-co/agenticos/issues/1412) adds the HIPAA and SOC 2 mapping |
| Public surfaces | A hosted page's visitor key is random, never derived from the person; admission and uploads are rate-limited per address in Redis and the address is not stored | [Channels](channels.md#a-hosted-page) |
| Legal notices | The deployment's own Terms and Privacy URLs replace the built-in pages | [The deployment](deployment.md#identity) |

### Traces

`instrument_pydantic_ai()` runs with the library's default, so a span holds the
user's message, the model's answer and every tool argument and result. With
`LOGFIRE_TOKEN` unset and no `observability` secret on any agent, nothing is
sent and the trace id is still recorded locally. A deployment that needs traces
before [#1413](https://github.com/vstorm-co/agenticos/issues/1413) lands has
one choice: a Logfire project whose terms and region it has accepted, knowing
the content goes with the timing.

### What deletion reaches

Deleting is what the product does today when somebody asks; scheduled
retention is [#1420](https://github.com/vstorm-co/agenticos/issues/1420).

| Action | Removes | Leaves |
|---|---|---|
| `DELETE /conversations/{id}` (the owner) | The conversation, its messages, tool calls, ratings, shares and `chat_files` rows, by cascade; a container workspace is purged through `purge_for_conversation` | **The attachments' bytes under `MEDIA_DIR`.** No route deletes a chat file; the only code path that unlinks one discards a channel bot's orphaned upload. Run rows and manifests that named the conversation keep their prompt copy. Tracked in [#1421](https://github.com/vstorm-co/agenticos/issues/1421) |
| `DELETE /memory/person/{user_id}` (the person, or `members:manage`) | Every `agent_memory_files` row keyed to the person across the organization's agents, and the same in each bound mem0 store | Notes keyed to a group chat the person spoke in |
| `DELETE /users/{id}` | The account, its sessions, its personal organization and personal collections with their vector tables and files, by explicit teardown; conversations and chat files by cascade | Audit entries naming the actor id; messages in shared conversations; the attachment bytes above. The inventory of each is [#1421](https://github.com/vstorm-co/agenticos/issues/1421)'s deliverable |
| Deleting a document or a collection | The rows, the vector table and the stored file, through a durable flow after commit | Nothing, once the flow has run; `sync_logs` counts remain |
| Deleting an organization | Everything scoped to it, with the same deferred teardown | Personal collections that merely carried the id |

None of these reach a backup. A restore brings back what was erased, so the
backup expiry is part of the retention policy and is written down with it.

## What a deployment has to decide and obtain

The software cannot supply any of these. Each is evidence the review will
ask for, distinct from the technical capability that makes it possible.

- **A processing agreement with each configured sub-processor** - every
  provider a `model_profiles` or `organization_secrets` row names, the
  embedding provider, LlamaCloud if a collection uses it, Brave or Exa, the
  mem0 host, Logfire, the SMTP relay and Google if sign-in is enabled.
- **A data location statement per provider**, matched to the `base_url` each
  profile actually uses. A provider with an EU endpoint is only in the EU if
  the profile says so.
- **A training exclusion per provider**: the account setting or contract term
  under which API data is not used for training. The platform's own position
  is one sentence - it trains nothing - and the rest is theirs.
- **A processing agreement with Vstorm**, only if Vstorm operates the
  deployment.
- **A retention schedule** for conversations, files, memory, documents, runs
  and audit, and the backup expiry beside it. Until
  [#1420](https://github.com/vstorm-co/agenticos/issues/1420) enforces one,
  retention is a manual deletion.
- **Disk or volume encryption** on the database host, the media volume and the
  sandbox host, since the application does not encrypt content itself.
- **The legal pages** the deployment links to, and who answers an access or
  erasure request while [#1421](https://github.com/vstorm-co/agenticos/issues/1421)
  is open.

## Verifying one deployment

Reproducible checks, from the host, against the running deployment. Each
prints facts the review can attach; none prints a credential or a person's
data. Run the commands from `backend/`, or through `docker compose exec api`.

```bash
# 1. Can it run, and are the store connections encrypted? `postgres` reports
#    the TLS state of the connection the doctor itself made.
uv run agenticos cmd doctor

# 2. Every sealed credential still opens under the configured master keys.
uv run agenticos cmd vault-rotate --dry-run

# 3. The settings that decide what leaves. Empty is the quiet answer.
env | grep -E '^(ENVIRONMENT|LOGFIRE_TOKEN|LOGFIRE_BASE_URL|OPENROUTER_API_KEY|LLAMAPARSE_API_KEY|LITEPARSE_OCR_SERVER_URL|MEM0_ALLOWED_HOSTS|POSTGRES_SSLMODE|REDIS_SSL|SMTP_TLS|LOG_PROVIDER_WRITE_TO_DISK|RATE_LIMIT_TRUST_FORWARDED_FOR)=' \
  | sed -E 's/(KEY|TOKEN)=.+/\1=<set>/'
```

`LOG_PROVIDER_WRITE_TO_DISK` must be `false` outside development: the logging
email provider writes whole mail bodies to disk when it is on.

```sql
-- 4. Every provider and endpoint an agent can reach, without the keys.
SELECT o.name AS organization, p.label, p.provider, p.model, p.base_url
FROM model_profiles p JOIN organizations o ON o.id = p.organization_id
ORDER BY 1, 2;

-- Profiles that speak plain HTTP. Each must point at the deployment's own
-- network; anything else sends prompts and the key in clear.
SELECT label, provider, base_url FROM model_profiles WHERE base_url LIKE 'http://%';

SELECT o.name AS organization, s.purpose, s.kind, s.name
FROM organization_secrets s JOIN organizations o ON o.id = s.organization_id
ORDER BY 1, 2;

SELECT name, embedding_provider, embedding_model FROM knowledge_bases ORDER BY 1;
SELECT scope, name, url, auth_type FROM mcp_connections WHERE is_enabled ORDER BY 1, 2;
SELECT name, connector_type, collection_name FROM sync_sources WHERE is_active ORDER BY 2, 1;

-- 5. Agents whose runs are traced to a project of their own.
SELECT a.slug, v.version
FROM agent_versions v JOIN agents a ON a.id = v.agent_id
WHERE v.spec -> 'observability' ->> 'token_secret_id' IS NOT NULL;

-- 6. What retention would have to reach. Adjust the age to the schedule decided.
SELECT 'conversations' AS store, count(*) FROM conversations WHERE created_at < now() - interval '365 days'
UNION ALL SELECT 'agent_runs', count(*) FROM agent_runs WHERE created_at < now() - interval '365 days'
UNION ALL SELECT 'audit', count(*) FROM app_admin_audit_logs WHERE created_at < now() - interval '365 days'
UNION ALL SELECT 'agent_memory_files', count(*) FROM agent_memory_files
UNION ALL SELECT 'chat_files', count(*) FROM chat_files;
```

```bash
# 7. Files whose rows are gone. Every path under MEDIA_DIR should be named by a
#    chat_files, rag_documents, users or agent_embeds row; a chat_files row
#    cascades away with its message while the file stays, so the difference
#    grows with every deleted conversation (see "What deletion reaches").
du -sh "${MEDIA_DIR:-./media}"
find "${MEDIA_DIR:-./media}" -type f | wc -l
```

Attach the output of 1 to 6 to the review together with the agreements from the
previous section. Item 7 is a size to watch until
[#1421](https://github.com/vstorm-co/agenticos/issues/1421) removes the bytes
with the conversation.

## Open conditions for a first rollout

Stated for the deployment this page was written against, and true of any
deployment until each closes.

**In the code, tracked:**

- Traces carry full content - [#1413](https://github.com/vstorm-co/agenticos/issues/1413).
- No scheduled retention - [#1420](https://github.com/vstorm-co/agenticos/issues/1420).
- Attachment bytes survive their conversation; no personal data export; the
  erasure inventory - [#1421](https://github.com/vstorm-co/agenticos/issues/1421).
- No audit export or tamper evidence - [#1422](https://github.com/vstorm-co/agenticos/issues/1422).
- Files on local disk only, encrypted by the volume or not at all - [#1423](https://github.com/vstorm-co/agenticos/issues/1423).
- No self-service view of one's own memory - [#1594](https://github.com/vstorm-co/agenticos/issues/1594).
- No OIDC sign-in - [#1419](https://github.com/vstorm-co/agenticos/issues/1419).
- The HIPAA and SOC 2 controls matrix - [#1412](https://github.com/vstorm-co/agenticos/issues/1412).

**In the deployment, decided by its operator:** the agreements, locations,
training exclusions, retention schedule, backup expiry, disk encryption and
legal pages of the previous section.

A review that finds every row above either closed or accepted in writing has
what this page can give it. The rest is the deployment's.
