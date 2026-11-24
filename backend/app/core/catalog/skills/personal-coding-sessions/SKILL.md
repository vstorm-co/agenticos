---
name: personal-coding-sessions
description: Choose, continue and review private Claude Code and Codex sessions using the initiating person's connected account.
category: engineering
---

# Work with personal coding sessions

Use this method for a coding task that benefits from native Claude Code or Codex
history. The runtime tool contract determines which execution modes are available.
A skill grants no account, tool or authorization.

Give the coding agent the objective, source location, relevant constraints and a
concrete completion check. Prefer one agent for a bounded task. A second agent is
useful for independent work or an explicit review; avoid delegating routine reads
or starting several expensive sessions for a simple question.

In personal cloud mode choose `harness=claude_code` or `harness=codex` and a stable,
short session name such as `api` or `ui`. Respect the person's explicit choice.
The same name and account continue native CLI history and files in a private
container for this conversation. Different names have separate files, initialized
from the source at first use. `fresh_session=true` resets native conversation
history, preserving those files. It is not a way to obtain a clean source tree.

Tasks using one account wait for its credential lease. Different accounts can
work concurrently, including Claude Code and Codex. Do not promise a strict FIFO
order or unlimited persistence: queue waits are bounded and sandbox idle expiry
can remove a session. If state is unavailable or a failed task was discarded,
say so and start a new name deliberately rather than claiming continuation.

A missing account needs the person's connection in Settings → Profile. Never
fall back to an organization key, another person's account, a scheduled identity
or a shared source to avoid that refusal. Keep credentials out of tasks, files,
reports and memory.

Review the result archive and diff against the reported initial source revision.
Check relevant tests, conflicts with newer source changes and the actual result.
Parallel sessions do not synchronize or merge files. Integrate changes explicitly
into the intended source only after reviewing them under the person's authority.
Report what changed, what was checked and what still needs a decision.
