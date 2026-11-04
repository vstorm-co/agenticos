# PR #2326 completion

Scope agreed on 2026-10-24: finish the desktop/mobile PR, adopt the staged local
file panel, add paired-device local MCP and Ollama/OpenAI-compatible models,
and prepare installers, signed updates and mobile distribution. Signing and
store publication are configured through CI secrets; no release or merge is
requested. Work proceeds without subagents.

Acceptance criteria:

- Local files are readable only inside native grants, with bounded traversal
  and reads, and covered by native and frontend tests.
- Native live activities, budgets, device push, offline dashboard and install
  prompts have working tests rather than stale fixtures.
- Device workspaces, local desktop, take-over, E2B, local triggers and session
  push links have refusal and failure coverage.
- Local service endpoints are approved on the computer; the server cannot
  choose an arbitrary loopback URL or command. Only the initiating person's
  paired session is used. No automatic cloud fallback for a local model.
- Desktop/mobile toolchains run in CI. Release workflows build installers and
  APK/IPA artifacts, verify updater signatures and document required secrets.
- Published documentation and translations describe delivered behavior.
- Focused local tests and lint pass, then CI is checked for the pushed SHA.

Baseline: head 4617e7141; 654 changed paths against local origin/main. Existing
worktree contains 12 staged paths for local files. CI 40036431589: frontend
MobileBridge mocks fail, security audit reports fastmcp/filelock, backend test
job cancelled; e2e and docs passed. Focused backend baseline: 406 pass, 10 fail
in stale computer-use expectations after desktop default changed to auto.


Implementation update:

- Adopted the local file panel; bounded native traversal and reads and excluded
  symlinks. Added approved loopback model/MCP grants and per-run choices.
- Added the local Chromium transport for existing browser tools, disposable
  profiles, native consent and cleanup on completion/disconnect/cancellation.
- Added native CI, installer/updater/APK/TestFlight workflows and version
  preparation covering Apple extensions; documented secrets in all four locales.
- Fixed desktop-only hooks running on mobile and compacted the start checklist.
- Updated vulnerable fastmcp/filelock locks and regenerated license notices.
- Focused checks passed: local service adapters, device workspace errors, E2B
  tenant credentials, local browser transport, local access, runner wiring,
  release preparation, native file/service tests and frontend controls.
- Full suites have not run locally. CI for the pushed commit is the remaining
  verification. Native signing, TestFlight and real-device push need CI secrets
  and operator accounts. Manual UI exploration stopped at the user's request;
  remaining UI work proceeds through code review.
