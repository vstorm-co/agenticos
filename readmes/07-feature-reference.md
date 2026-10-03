# AgenticOS

Self-hosted, open-source workspace for building, sharing and running AI agents. This README is a reference: everything that ships, in tables, with the limits next to it.

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

**Contents:** [Capabilities](#built-in-capabilities) · [Surfaces](#where-agents-answer) · [Knowledge](#knowledge-bases) · [Models](#models) · [Access](#access-and-sign-in) · [Governance](#governance) · [Operations](#operations) · [Limits](#limits)

<img src="../docs/assets/screens/light/agent-builder.png" alt="The agent builder." width="100%">

## Built-in capabilities

26 capabilities, switched on per agent. *Key* = needs a provider key in the vault. *Sandbox* = needs a container connection.

| Group | Capability | What it does |
|---|---|---|
| Knowledge | Knowledge search | Searches bound collections and cites sources |
| | Skills | Loads written procedures when relevant |
| | Context | Glossary, policies, house style, in the prompt or on demand |
| | Memory files | Notes the agent keeps across conversations |
| | Memory (mem0) | An external memory service (*key*) |
| | Conversation search | The speaker's own past conversations |
| Web | Web search | DuckDuckGo by default; Tavily, Brave or Exa (*key*) |
| | Web fetch | Reads the page behind a URL, SSRF-guarded |
| | Browser automation | Acts on a real page (*key*, add-on, operator-run Chromium) |
| | Browser-use | Open-ended web tasks; wired but not installable yet |
| Files and code | Run Python | Short computation, no network, no filesystem |
| | Files and shell | A persistent workspace with files and commands (*sandbox*) |
| | Charts | Draws the numbers it found |
| | Image generation | OpenAI or Google (*key*) |
| | Artifacts | Publishes a page under a stable link |
| Working | Delegation | Hands part of a job to other agents |
| | Planning | A checklist for multi-step work |
| | Thinking | Reasons before answering |
| | Tool search | Finds tools in a large set |
| | Date and time | Today's date in the instructions |
| | System reminders | Re-states guidance mid-run |
| Safety and limits | Guardrails | Redacts secrets and personal data, or blocks on keywords |
| | Context management | Trims long histories |
| | Media offload | Stores images outside the prompt |
| | Tool output limits | Keeps oversized results in check |
| Channels | Channel lookup | Who is in the Slack, Telegram or Mattermost channel (per bot) |

Plus any tool from a connected MCP server: 99 curated servers and 5,703 registry listings. [Capability reference](https://vstorm-co.github.io/agenticos/reference/capabilities/) · [MCP](https://vstorm-co.github.io/agenticos/mcp/)

## Where agents answer

| Surface | Notes |
|---|---|
| Web chat | In the console, for members |
| Website widget | Allowed origins required; public or signed visitors |
| Hosted page | A shareable link with its own rate limit, budget and pause switch |
| HTTP API | One answer per call, authenticated as a member |
| WebSocket | Token-by-token streaming |
| Slack | Socket Mode or HTTP |
| Mattermost | Bot token and server URL |
| Telegram | Webhook with a secret, or polling |

Routines start agents on a schedule (interval or cron, UTC) or on an event: GitHub, Gmail (polled every minute) or a signed webhook. [Channels](https://vstorm-co.github.io/agenticos/channels/) · [Routines](https://vstorm-co.github.io/agenticos/triggers/)

## Knowledge bases

| Area | What ships |
|---|---|
| Sync sources | Google Drive, S3/MinIO, website, Git repository, SharePoint and OneDrive; scheduled or manual; full or changes only |
| Upload formats | txt, md, docx always; pdf, office files and images depending on the parser |
| Parsers | PyMuPDF (local, default), LiteParse (local, OCR), LlamaParse (cloud, key); per collection or per upload |
| Chunking | Recursive, Markdown or fixed; size and overlap per collection |
| Embeddings | OpenAI, OpenRouter, or local Ollama models; fixed per collection |
| Retrieval | Vector search in pgvector with filters, optional query expansion and parent context, citations |
| Access | Personal, organisation or deployment collections; shared with people or groups |

[File processing](https://vstorm-co.github.io/agenticos/file-processing/) · [Sync sources](https://vstorm-co.github.io/agenticos/howto/configure-sync-sources/)

## Models

<img src="assets/model-providers.webp" alt="27 model providers: hosted, your cloud contract, and on your hardware." width="100%">

## Access and sign-in

| Area | What ships |
|---|---|
| Roles | Owner, Admin, Builder, Operator, Member, Viewer (defined in code) |
| Sharing | Private, team or organisation visibility, plus read, use or edit grants to people and groups |
| Sign-in | Email and password, magic link, Google, OIDC (Entra ID, Okta, Keycloak, Auth0, Authentik, Google Workspace), LDAP, Kerberos |
| Directory | Directory groups mapped to a role and a group at sign-in |
| Sessions | 30-minute access, 7-day refresh with reuse detection, revocable |

## Governance

| Control | What it does |
|---|---|
| Budgets | Monthly caps per agent and organisation, checked before each model request |
| Approvals | Per tool: required, never or default; the run waits for a person; expires after 72 hours |
| Guardrails | Redaction of secrets, emails, IBANs, card numbers, US SSNs; keyword block |
| Alerts | Budget, approval and usage alerts, in the app and by email |
| Activity | Run history with version, tools, tokens and cost; CSV export |
| Audit | Hash-chained per organisation, verifiable, CSV/JSONL export |
| Versions | Publish freezes a version; dev, staging and production point at versions; YAML export |

## Operations

| Area | What ships |
|---|---|
| Install | One script; Docker Compose ≥ 2.24; WSL2 on Windows |
| Sizing | 4 vCPU and 8 GB RAM run it; two API workers suit a team of ten |
| Upgrade | Pin a version; migrations run on start |
| Backup | PostgreSQL, the media volume and the settings file with the vault key |
| Tracing | Built-in run history; Logfire optional |
| Languages | Console in English, Polish and German; documentation also in Spanish |

## Limits

| Not today | Instead |
|---|---|
| MFA, SAML, SCIM | MFA through your identity provider over OIDC |
| Source ACL mirroring | Scope each source's credential and share the collection |
| Reranking | Vector search with options |
| Kubernetes, multi-host scaling | One host with Docker Compose |
| Zero-downtime upgrades | Plan a short maintenance window |
| Strict budgets under parallel runs | Run agents through one queue |
| Built-in Microsoft 365 triggers | Outlook via a third-party MCP service |
| Visual workflow builder | In development |

[Apache License 2.0](../LICENSE) · Built by [Vstorm](https://vstorm.co)
