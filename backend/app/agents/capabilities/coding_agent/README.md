# coding_agent

Claude Code or Codex, doing software work in the agent's own sandbox (#2092).

## What it is

Two tools. `plan_code_change` runs the harness read-only - Claude Code in its
`plan` permission mode, Codex with its sandbox set to `read-only` - and returns
the plan or the finding. `apply_code_change` runs it with permission to edit and
execute, and is side-effecting: the tool to set **Always ask** on, so a person
approves each change. Like every gate it is off until somebody sets it. Applying usually continues the planning
session (`session_id`), so the harness keeps what it read.

An agent with this capability is a *coding agent*. Another agent hands it work
through ordinary delegation, the same way it reaches any specialist.

## Why headless through the sandbox's shell, not ACP

The Agent Client Protocol drives a harness over a long-lived stdio session. The
sandbox runs a command to completion and returns its output; it has no
interactive session to hold one open in. Both harnesses also run headless with a
machine-readable event stream - `claude -p --output-format stream-json`,
`codex exec --json` - which is what OpenClaw's CLI backends use, and that is what
this does: one command per task, its events written to a file in the workspace,
read back and parsed. The cost is that the steps reach the conversation when the
task finishes rather than as it runs.

## Why one approval per change

A harness asks permission per file and per command when a person sits at its
terminal. Nobody does here, and forwarding each of those prompts through the
platform would make a person approve forty edits to accept one change. So the
platform asks once, at `apply_code_change` when it is gated, after the plan has
been shown, and the harness runs with its own prompts off either way: Claude Code with
`--dangerously-skip-permissions` (and `IS_SANDBOX=1`, which it asks for when run
as root), Codex with `--dangerously-bypass-approvals-and-sandbox`. The container
is the boundary, which is what both flags are documented for.

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
- An API key in the vault: Anthropic's for Claude Code, OpenAI's for Codex. For
  Claude Code behind a gateway such as OpenRouter, `base_url` names it and the key
  is the gateway's. The key reaches the command as an environment variable,
  never on its command line.

## What it does not do

- Stream the harness's steps while it works.
- Forward the harness's own permission prompts.
- Run on the `state` workspace, which has no shell.
