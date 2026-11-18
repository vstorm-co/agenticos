# Native primary conversation runtimes

The primary runtime is a per-conversation Desktop selection, separate from a
Pydantic AI subscription model profile, coding-task delegation, Background topics
and A2A remote agents. It replaces the model making the conversation's answer;
it does not ask another hosted model to delegate the user's request.

## Transport decision

| Candidate | Decision |
| --- | --- |
| Pinned Codex ACP adapter | Reuse the owned Desktop process/session lifecycle, streamed updates, permission policy and scoped MCP bridge. |
| Codex App Server directly | Its thread/turn API is a valid alternative, but would introduce a second transport owner and a second implementation of session admission, tools, cancellation and recovery. No direct App Server integration is claimed. |
| Pinned Claude Code ACP adapter | Use the same narrow ACP boundary; the adapter owns its official SDK/CLI transport. Authentication remains in the unmodified vendor CLI. |
| Claude Agent SDK directly | A valid separate boundary for hosted API/cloud execution, but not a reason to import or broker a CLI consumer grant. No hosted subscription runtime is claimed. |

This decision reuses already pinned dependencies, rather than installing a new
version or treating another application's OAuth identity as authorization.
Codex App Server was compared with the existing ACP session operations; Claude
Agent SDK was compared with the existing adapter's process ownership and tool
configuration. Real-account compatibility remains acceptance evidence, not an
inference from another assistant supporting the provider.

## Ownership and recovery

`NativeModelSpec` builds the primary Pydantic AI model without resolving the
profile's cloud credential. A capability binds the owned run context for the
SDK's non-streaming signature; streaming also receives it directly. The model
sends native text updates to the normal answer stream and native tool activity
to the existing Activity transport. Platform tools still execute through the
prepared tool manager, resource authority, approvals and output screening.

Native identity includes tenant, initiating person, agent, conversation, folder,
harness, model, access policy and an explicitly selected session epoch. Desktop
adds its connection and native folder identity. A settled response records an
opaque session ID and a digest of the visible platform history. Later turns
verify both before loading that session, and forward only new conversation
context plus current instructions. A missing or altered receipt, missing native
state or an uncertain prior admission refuses automatic continuation. Reset is
explicit and retains the platform chat; effects must be checked before continuing.

The native CLI owns its context management, tools and credential refresh. The
platform never imports a CLI grant, borrows an organization key on failure, or
pretends that native internal requests and subscription spend are measured API
usage. A runtime change or reset selects a different epoch/scope. Cancellation
closes the owned process tree and pending tool/question operations; unknown
external effects are not rolled back or retried.

## Initial supported surface

Only the initiating member's private, unshared Desktop text web chat is supported.
A full-access native folder is required because the CLI is not an OS sandbox.
The separate read-only runtime policy refuses native writes/commands and exposes
only platform tools classified read-only by the canonical isolation classifier;
unknown tools are denied. Editing retains the agent's existing approval policy.
Forwarded platform calls are capped by the run's tool-call limit as well as its
budgets. Vendor-internal requests, tokens, tool calls and charges remain opaque.

Structured answers, multimodal prompts, Code Mode, platform compaction, reviewers
and authored model-setting overrides are refused explicitly. Auxiliary inference
needs its own supported provider configuration; it must not recursively borrow
the active primary CLI session. Hosted/API/voice/scheduled execution and team
callers cannot borrow the Desktop owner's account. This is a deliberate surface
contract, not a claim that every platform feature is a native CLI feature.

`CODEX_NATIVE_CONVERSATION_ENABLED` defaults to false. The operator enables it only for an eligible local/open-source deployment or an approved use; App Server authentication is not permitted for commercial or hosted services without the applicable approval. The switch is advertised by the provider catalog and enforced before credential/profile resolution. Account changes through Desktop stop and await only that builtin runtime, clear its saved continuations and consent, and serialize new launches against the account operation. Manual changes outside Desktop require a reset.

The account's subscription/API/cloud choice and provider eligibility belong to
the CLI and its operator. Using an unmodified CLI does not establish subscription
entitlement or permission for a hosted SDK product. Claude product deployments
must verify current vendor conditions and prefer API/cloud credentials where
required; account and legal acceptance remain explicit PR follow-up conditions.

## Sources checked

- [Codex App Server](https://learn.chatgpt.com/docs/app-server) describes its thread/turn and account operations.
- [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview) distinguishes the SDK, CLI and hosted execution.
- [Claude Code legal conditions](https://code.claude.com/docs/en/legal-and-compliance) require an unmodified binary, user-owned authentication and direct user billing; SDK/deployment eligibility must be verified separately.
- `desktop/runtime/package.json` and its lockfile record the ACP/SDK versions actually shipped by this implementation.

`CLAUDE_NATIVE_CONVERSATION_ENABLED` also defaults to false and is enforced independently. The SDK documentation requires prior approval to offer claude.ai login or consumer rate limits in a third-party product. Verify API/cloud credential eligibility or obtain that approval before enabling; never disable authentication methods inside the vendor binary. The feature is named “Claude Agent” under the SDK branding rules.
