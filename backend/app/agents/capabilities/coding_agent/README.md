# coding_agent

Claude Code or Codex, doing software work in the agent's own sandbox (#2092).

## What it is

One tool, `run_coding_agent`. The agent hands Claude Code or Codex a whole task;
the harness works on it in the sandbox until it is done, and the chat shows it
working. What the harness may do is the binding's `access`, not the model's
choice: `edit` changes files and runs commands, `read_only` reads and answers
(Claude Code only - Codex's read-only mode is its own sandbox, which cannot start
inside the container, and then even `cat` fails). Whether a person approves each
task first is the capability's approval, set to **Always ask**; the capability
declares `tool_settings=False`, so the Builder shows no per-tool tab for a tool
that *is* the capability.

The tasks of one conversation continue one harness session. The session id is
kept in the sandbox at `.agenticos/coding-agent/<harness>.session`, the second task
resumes it, `fresh_session` starts over, and a session the sandbox lost (a fresh
container) starts over by itself, once.

An agent with this capability is a *coding agent*. Another agent hands it work
through ordinary delegation, the same way it reaches any specialist.

## Detached, and watched

The harness is started in a session of its own (`setsid nohup`) with its events
written to a file, and the platform polls that file - one command per poll that
answers with the new bytes, base64, and the exit code once there is one
(`_task.py`). Two reasons. A coding task outlives the sandbox service's ceiling
for one command. And a person should see Claude Code read, edit and run tests as
it does them: each event becomes the delegation frames the chat already draws
(`_narration.py`, `app.agents.subagent_events`), so the harness gets a panel of
its own under its own mark, nested under a delegate that handed the task on. A
timed-out task, and a run that is cancelled, has its process group stopped.

## Why headless through the sandbox's shell, not ACP

The Agent Client Protocol drives a harness over a long-lived stdio session. The
sandbox runs commands and returns their output; it holds no interactive session
to keep one open in. Both harnesses also run headless with a machine-readable
event stream - `claude -p --output-format stream-json`, `codex exec --json` -
which is what OpenClaw's CLI backends use, and that is what this does.

## Why one approval per task

A harness asks permission per file and per command when a person sits at its
terminal. Nobody does here, and forwarding each of those prompts through the
platform would make a person approve forty edits to accept one change. So the
platform asks once, before the task, when the approval is set, and the harness
runs with its own prompts off at `edit`: Claude Code with
`--dangerously-skip-permissions` (and `IS_SANDBOX=1`, which it asks for when run
as root), Codex with `--dangerously-bypass-approvals-and-sandbox`. The container
is the boundary, which is what both flags are documented for. At `read_only`
Claude Code runs in its default permission mode without its editing tools and
with only reading commands allowed, and is told nobody can approve anything else
(it otherwise tells the person to "approve the deletion").

## What it costs

Each harness reports its tokens per model, and they are booked to the run's
ledger like any model call, so budgets apply and the run's cost includes them.
The budget is checked before each task. Codex does not name its model in its
events, so a binding with no `model` books Codex's usage unpriced and the run's
cost says it is partial.

## What it needs

- The `sandbox` capability on the `service` backend with the shell on, which
  publish checks.
- A runtime with the harness installed. `workbench` pins Claude Code and Codex.
- A credential in the vault. Claude Code: an Anthropic API key, or the token
  `claude setup-token` prints for a Claude subscription (told apart by its
  `sk-ant-oat` prefix, and sent as `CLAUDE_CODE_OAUTH_TOKEN`); behind a gateway
  such as OpenRouter, `base_url` names it and the key is the gateway's. Codex: an
  OpenAI API key, or a ChatGPT sign-in, which is written to `~/.codex/auth.json`
  outside the workspace for the task and read back afterwards, so a pair Codex
  refreshed is sealed over the same secret - its refresh token is single-use.
  Codex's `auth.json` also wants an `id_token`, which the sign-in does not keep;
  the CLI reads only its claims, so one is made of the access token's.
  A credential reaches the command through its environment, never on its
  command line.

## What it does not do

- Forward the harness's own permission prompts.
- Run Codex read-only.
- Run on the `state` workspace, which has no shell.
