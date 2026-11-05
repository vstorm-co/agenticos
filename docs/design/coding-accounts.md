# Personal coding accounts and shared projects

Status: implemented, 2026-11-05. Provider sign-in and real CLI acceptance tests
remain manual; no live credential is required by the regression suite.

## Account and execution contract

| Execution | Credential | Workspace and result |
| --- | --- | --- |
| In the agent's sandbox | Explicit tool-level organization credential | Existing workspace; changes appear in the task diff |
| Private cloud task with my account | Initiating person's enabled profile connection in this organization | Disposable run-scoped container; diff and ZIP returned to the conversation |
| On this computer | Local CLI sign-in | Explicitly approved local folder; no automatic upload or cloud fallback |

Connect an Anthropic API key/Claude setup token, OpenAI API key, or a fresh ChatGPT
sign-in under **Settings → Profile → Coding accounts**. Each person has at most
one connection per harness per organization. Credentials use `VaultScope.user`;
only owner metadata is returned by the API. Consent defaults off. Enable, disable
and disconnect are owner-only and generation checked. An organization administrator
cannot read or borrow another person's account. Vault rotation and personal data
export include these accounts; export excludes credentials.

Choose `coding_agent.runs_on: personal_sandbox` in the agent's tool settings.
It requires a service sandbox and an authenticated, person-initiated web/API
conversation. API keys, impersonation, schedules, channel jobs and publisher
fallbacks cannot use profile accounts. Delegates sharing that run's workspace
inherit its initiating authority. Missing consent is an explicit refusal; neither
the tool key nor somebody else's account is substituted.

## Shared project work

The server copies source files into a **different run-scoped container**, never
just a second directory in the shared container. The task receives a new harness
session, its own credential home and a content/mode snapshot hash. Symlinks,
platform directories, Git internals and dependency caches are excluded. Executable
bits are retained. Limits are 500 files, 1 MiB per file and 16 MiB of source content.
Oversized or invalid copies fail explicitly. The selected sandbox image must
provide Python 3 and the selected coding harness.

Results appear in chat as a final report, a bounded diff and
`coding-results/<task-id>.zip`. The ZIP contains the resulting source snapshot;
deletions are represented by the diff. Both follow the conversation's existing
read policy. Shared source files are **not automatically changed**. Review the
patch/archive before applying it. There is no conflict-resolving publish button,
automatic merge or local/cloud synchronization.

Personal tasks suppress live harness payloads until credential redaction can cover
the initial and refreshed tokens. Known credential material is removed from reports
and patches; an archive containing it is refused. This is not a general-purpose
secret scanner. Private task containers are destroyed in terminal cleanup; cleanup
failure is visible. The lease allows only one active task per profile connection
across workers, so refresh writes are serialized. The latest token pair uses a
compare-and-swap against the pair originally read and keeps the account identity.

While work runs, a two-second watcher rechecks organization membership, account
consent/generation and project access. Revocation cancels work and prevents result
export; cancellation and failure release the lease and close the container.
A user's disable/disconnect removes the platform grant, not the provider's external
grant. Revoke a ChatGPT grant in ChatGPT Settings at OpenAI as well.

## Desktop and authentication boundaries

Desktop continues to use its managed Node/ACP adapter, the local CLI's existing
sign-in and approved folder. Its status/preferences are also available from the
profile in the desktop shell. Local auth files are never imported into the server.
A local signed-in status is not proof of identity equality with an AgenticOS user.
Existing account/server changes continue to clear native grants.

Cloud ChatGPT sign-in reuses the platform's existing caller/org-bound Codex OAuth
flow and `OpenAICodexSecret` refresh contract. It does **not** implement a new dynamic
SIWC client registration or import arbitrary CLI `auth.json`. Those protocols must
not be mixed. No remote session transfer is implemented. Account entitlement and
provider terms still need the user's real-provider acceptance test.

Official sources checked on 2026-11-05:

- [OpenAI account registrations and sessions](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)
- [OpenAI Codex app-server integration](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server)
- [OpenAI self-hosted VM credential transfer](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms)

Upgrade API and workers together after applying
`0290_personal_coding_accounts.py`. Existing tool-level credentials and desktop
bindings retain their behavior. Private cloud execution is opt-in.
