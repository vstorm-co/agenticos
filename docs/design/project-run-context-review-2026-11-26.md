# Project context, execution and file origins review

This completes the runtime part of the project work in #3299. It uses the existing
project workspace and persistence services; it does not introduce a second file
store, synchronization, revision checkout/publish flow or automatic mounts.

## Contract

- Projects capability offers discovery, scoped selection and bounded UTF-8 file
  operations without granting Sandbox commands. Built-in AgenticOS and Architect
  receive it through their normal template-content refresh.
- Project chat uploads and materialized resources stay in the project file
  namespace. Command execution separately selects Agent or Project; ordinary chats
  default to Agent, attached project chats to Project. Explicit native folder
  consent remains authoritative. Disabled author capabilities stay disabled.
- Dynamic selections in private web/channel runs are run-local. Approval/Q&A
  checkpoints retain selection, executor, generation and the fact that private
  context was observed. A new ordinary user turn starts fresh. Names never grant
  access; models must search/select an authorized ID.
- Every project operation rechecks membership, live API-key authority, resource
  access, routine source ceilings and generation. Unknown channel room audiences
  and unrelated shared transcripts cannot receive private project context. An
  admitted shared project chat may use its own project. Clearing context cannot
  write already observed private context into a wider agent/channel workspace.
- A lazy independent Agent executor is opened at most once per run, uses the
  original configuration and identity, and remains open through output collection.
  It is closed by terminal cleanup. No credentials from a project are borrowed.
- Runs record workspace IDs and project IDs, including failure/cancellation;
  origins are references, never copies. Listing and concrete reads reauthorize.
  Project and Agent endpoints remain distinct, with no same-path fallback.
  Files from run-scoped workspaces remain temporary and are not promised after
  cleanup. Existing historical runs have no fabricated origin backfill.

## Compatibility and limits

`select_project_workspace` now selects files only. Command target changes are
explicit through `select_execution_target`; old dynamically selected checkpoints
without a generation must reselect or restart. Existing project chats retain their
Project default. Request fields omitted by old clients retain their previous API
idempotency fingerprint. Steering cannot switch the executor of an active attempt.

Projects text operations list at most 100 entries and accept 256 KB UTF-8 files.
They reject unknown sizes, unsupported binary text, reserved/escaping canonical
paths and conflicting edits after a read. Canonical aliases share the read guard.
This is not a versioned document store or a file transfer feature. Shell execution
retains its configured approvals and can perform arbitrary authorized project edits;
the text-tool conflict guard is not a transactional shell filesystem.

## Verification

- Scoped project port and capability tests: 59 passed, 100% statements and branches
  across the port, capability and Sandbox selector modules; no provider/model calls.
- Runner, API, chat-frame and workspace boundaries: 93 passed in the selected batch,
  including the unchanged historical request fingerprint and independent output
  collection while project files remain untouched.
- Real PostgreSQL tests cover concrete file origins, same-path separation, revoked
  project grants, tenant isolation, failed/cancelled references and steering target
  identity. Shipped-agent refresh tests preserve the chosen model.
- Scratch pgvector database: empty-to-head upgrade, `alembic check`, one downgrade,
  re-upgrade and schema check. Migration `0371_run_workspace_origins.py` adds only
  an empty-by-default JSONB reference column.
- Scoped ty, Ruff, documentation translation/guide guards and strict four-language
  MkDocs build. Final combined-train CI and runtime UI verification remain separate
  evidence; this backend worktree has no live-model or production changes.
