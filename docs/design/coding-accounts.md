# Personal coding accounts and shared projects

Status: proposal, 2026-11-04. Personal profile connections and isolated cloud
coding tasks described below are not implemented by the starter-default change.
The existing tool-level credential and desktop paths remain available.

## What exists

- `coding_agent` can run in a server sandbox with a selected credential, or on
  an approved desktop folder using that computer's coding-agent sign-in.
- Desktop prepares a pinned private Node/ACP runtime. Installation/status probing
  can find a system CLI, but coding sessions use the managed adapter; the exact
  binary/version need not be the one on the person's shell PATH.
- Local sessions are scoped to organization, initiating user, agent, conversation,
  harness, access policy, approved root and desktop connection. AgenticOS does not
  upload the local CLI's authentication files to the server.
- The server refuses a ChatGPT subscription sign-in in a shared project, channel
  or agent sandbox: shell commands in the same container could read another
  person's tokens. A private directory alone is insufficient isolation.
- Local folders and shared project files do not synchronize automatically.
  Project membership grants no access to another member's disk.

## Recommended product contract

Keep three independent choices: the coding provider/account, where execution
happens, and which project files it may read or change. An agent's spec chooses
allowed execution modes and limits. The profile chooses the person's preferred
coding account. A task binds one resolved choice and displays it before execution.

| Execution | Credential | Workspace |
| --- | --- | --- |
| This computer | Initiator's local CLI sign-in | Their explicitly approved folder |
| Personal cloud task | Initiator's explicit profile connection | Isolated task environment and private credential home |
| Team automation | Explicit organization credential | Managed workspace under a defined service actor |

The local sign-in belongs to the operating-system account. A signed-in boolean
from the CLI does not prove it belongs to the current AgenticOS profile. Show the
selected harness/account explicitly; retain the existing grant reset on an
AgenticOS account/server change rather than silently associating identities.

A personal profile connection should be a user-owned credential sealed with the
existing `VaultScope.user`. Enabling its use in an organization is explicit and
revocable. Project access must not reveal or confer use of that credential.
Retain tool-selected organization credentials for managed team work; never fall
back from a missing personal sign-in to a different person's or a team credential.

In a shared chat, the person whose message starts the task owns its authentication
and usage. A later participant does not inherit that harness session. The audit
record identifies initiator, organization/project, account reference, execution
host, base revision and changes; it contains no tokens. Conversation transcripts
can be shared only under their existing project/chat policy.

## Concurrent project work

A personal cloud task needs a separate process/container security boundary,
private credential home and writable checkout. Git worktrees isolate edits, not
credentials; two worktrees in one shared Unix account are insufficient. Use a
checkout or task environment per task, rooted in an explicitly recorded project
revision. Each task returns a diff, tests and conflict status. Apply its result to
the shared revision only through an explicit publish step with revision checking;
never let two coding harnesses mutate the same working directory concurrently.
Projects that are file stores need the equivalent snapshot-and-conditional-apply
contract rather than an assumed Git repository.

An unattended routine must name an allowed actor and credential policy explicitly.
Using a personal account in background work requires separate consent, limits and
revocation. Local execution needs the owner's paired device online and its current
folder/operation grant; an offline device does not authorize cloud substitution.
An administrator's approval does not lend the administrator's coding account.

## Authentication research and implementation order

OpenAI documents an app-owned ChatGPT-plan OAuth registration and a Codex
app-server integration. This is a candidate for a personal profile connection,
not a reason to copy arbitrary existing CLI credential files. The SIWC registration
and transport must be distinguished from the existing Codex-specific credential
shape; do not feed a new registration into an older client's refresh path.
Accounts must retain
separate registration IDs, host IDs and refresh state. Model catalogs do not prove
account entitlement; actual inference must establish it. Remote session transfer
has documented attribution/revocation limitations that need a separate review.

1. Expose existing local harness status and preference coherently in profile/desktop
   settings; preserve current local sign-in and folder grants.
2. Add a typed user-owned connection, provider-specific registration/refresh/revoke
   adapter, explicit organization-use policy and per-account refresh serialization.
3. Add private cloud task isolation and revision-safe result application before
   allowing personal subscription credentials to act on shared project material.
4. Integrate task/account visibility, quotas and consented unattended execution.
   Keep the existing shared-sandbox refusal until these guarantees are tested.

Sources checked on 2026-11-04:

- [OpenAI account registrations and sessions](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)
- [OpenAI Codex app-server integration](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server)
- [OpenAI self-hosted VM credential transfer](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms)
- Existing implementation: `desktop/src-tauri/src/local_agents.rs`,
  `desktop/src-tauri/src/agent_session.rs`,
  `backend/app/agents/capabilities/coding_agent/_toolset.py`,
  `backend/app/services/openai_codex.py`, `docs/desktop.md` and `docs/projects.md`.
