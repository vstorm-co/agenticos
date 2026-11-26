# Provider subscriptions and external runtimes

Implementation contract for [#3108](https://github.com/vstorm-co/agenticos/issues/3108).
This is working design material, excluded from the published documentation site.
No provider is delivered merely because it appears in this plan.

## Existing boundaries

A model profile configures inference in the Pydantic AI loop. A coding harness
executes a delegated task, over ACP on Desktop and headless commands in a sandbox.
A remote A2A registration points at an already running service. Background topics
own independent conversations and durable delivery; they are not another runtime.

Keep those boundaries. A new account connection does not replace an agent's spec,
its capability grants or its execution backend. An external primary runtime needs
an explicit contract for native tools, approvals, session ownership and platform
MCP access; delegation support alone does not meet that requirement.

## Delivery order and commits

All integrations are tracked in #3108. The former provider issues are closed
for consolidation, not as evidence of delivery. Their full scope and acceptance
criteria are preserved in four comments:

- [Model providers](https://github.com/vstorm-co/agenticos/issues/3108#issuecomment-6964065769)
- [ACP runtimes](https://github.com/vstorm-co/agenticos/issues/3108#issuecomment-6964066361)
- [Primary runtimes](https://github.com/vstorm-co/agenticos/issues/3108#issuecomment-6964067016)
- [Pi and Muse runtimes](https://github.com/vstorm-co/agenticos/issues/3108#issuecomment-6964067647)

Keep a separate implementation commit for each integration or shared component,
including its regression coverage and behavior documentation. New commits refer
to #3108; the single PR closes only #3108. Shared work precedes provider commits. Do not create empty commits to count an unsupported integration as
implemented. The single pull request remains a draft until accepted scopes and
verification are complete.

| Archived issue | Integration | Delivery boundary |
|---|---|---|
| #3130 | Custom ACP agents | Extend the current Desktop executor with trusted configuration |
| #3109 | Google Antigravity | ACP runtime and vendor-owned Google sign-in |
| #3110 | GitHub Copilot | Pydantic AI provider; verify our OAuth application's entitlement |
| #3111 | ChatGPT plan sharing | Separate credentials from Codex; respect deployment eligibility |
| #3112 | Codex | Existing integration extended to a primary conversation runtime |
| #3113 | Claude Code | Existing integration extended without collecting Claude.ai tokens |
| #3114 | Grok | Vendor CLI runtime and account modes |
| #3115 | OpenCode | ACP runtime; free catalog, explicit Go key, custom providers |
| #3116 | Cursor | ACP runtime and supported account/key modes |
| #3117 | Cline | ACP runtime with owned process lifecycle |
| #3118 | Kimi Code | Account-scoped runtime; distinct from Moonshot API |
| #3119 | Devin | CLI runtime; do not imply a cloud-task API integration |
| #3120 | Mistral Vibe | Runtime account access; identify actual billing mode |
| #3121 | Hermes | ACP runtime and isolated account/memory state |
| #3122 | Pi | RPC runtime; distinct protocol from ACP |
| #3123 | Muse | Native SDK runtime; verify tool restriction and account contract |
| #3124 | Inception | Pi-backed execution; depends on #3122 |
| #3125 | DeepSeek | Optional Pi execution; existing direct provider remains |
| #3126 | OpenRouter | Optional Pi execution; existing direct provider remains |
| #3127 | Z.AI Coding Plan | Existing model adapter with an explicit plan endpoint |
| #3128 | MiniMax M Plan | Compatible model adapter and explicit subscription-key setup |
| #3129 | Qwen Code | Supported CLI account flow and verified runtime protocol |

## Trust and lifecycle

Only an authorized person configures executable paths and argument vectors.
Models choose registered identifiers, never commands or environment variables.
Device-local configuration stays bound to that device and its initiating person.
Server execution must not reinterpret a Desktop path as a server command.

Use negotiated ACP features. An unsupported session reload, model selection,
permission model or MCP transport must be refused explicitly. A sandbox that only
executes finite commands cannot silently become an interactive ACP pipe.

Keep platform credentials in the vault and vendor CLI grants with their supported
owner. Personal grants do not become organization credentials. Cancellation closes
owned processes and resources; uncertain external effects are not replayed.

Subscription allowance, API charges and unknown external spend are different
outcomes. Quota exhaustion cannot silently select a paid API or another account.

## Evidence required before completion

Focused deterministic tests cover authorization, protocol errors, cancellation,
credential selection and compatibility. Real-account smoke evidence establishes
actual account/model eligibility; mocks cannot do that. Record platform, runtime
version and credential mode without tokens, codes or account identifiers.

External requirements may block an individual provider. Official ChatGPT plan
sharing distinguishes local/OSS use from paid or remotely hosted use. Copilot must
accept our application's OAuth token, not merely authenticate it with GitHub.
Claude product integration has vendor-specific authentication requirements.
Unconfirmed eligibility and account smoke tests remain explicit acceptance
follow-ups in #3108 and PR comments. Continue independent implementation while
external requirements are pending; do not report those requirements as verified.

## References

- [Current coding capability](../reference/capabilities.md#coding-agent)
- [Remote A2A agents](../reference/capabilities.md#remote-agents)
- [Background topics](../console.md#background-topics)
- [Pydantic AI Copilot](https://pydantic.dev/docs/ai/models/github-copilot/)
- [ChatGPT plan sharing](https://developers.openai.com/siwc/token-sharing-open-source)
- [Claude integration requirements](https://code.claude.com/docs/en/legal-and-compliance)
