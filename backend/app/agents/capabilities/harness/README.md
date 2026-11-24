# harness

Claude Code or Codex, kept as a session the agent drives across turns (#TBD).

## What it is

Four tools, one session. `harness_start` opens a named session - Claude Code
or Codex in the agent's sandbox - with a first prompt; `harness_prompt` sends
it the next one; `harness_stop` closes it; `harness_sessions` lists the ones
a conversation has open. The session is the CLI's own: its id is kept in the
sandbox at `.agenticos/harness/<harness>-<conversation>[-<session>].session`,
the next prompt resumes it, and a session the sandbox lost (a fresh container)
starts over by itself, once. Starting a session by a name already open starts
it over.

What the harness may do is the binding's `access`, not the model's choice:
`edit` changes files and runs commands, `read_only` reads and answers (Claude
Code only - Codex's read-only mode is its own sandbox, which cannot start
inside the container). Which harness, which model, and the key are closed over
when the tools are built; the model chooses the session and what to say to it.
Whether a person approves each prompt first is the capability's approval; the
capability declares `tool_settings=False`, so the Builder shows no per-tool
tab for four tools that *are* the capability.

An agent with this capability is a *harness-backed agent*. Another agent
reaches it through ordinary delegation, the same way it reaches any
specialist. The gateway model that drives the session stays the one answering
the person; the session's answers are its own.

## How it differs from the coding agent

The coding agent hands one task to a harness and reports back. The harness
capability keeps the session open across turns: one session per line of work,
prompted as the work proceeds, so the session remembers what its earlier
prompts read and changed. The two must never continue each other's sessions,
so their session files live in different directories - `.agenticos/harness`
here, `.agenticos/coding-agent` there - and a harness session is never
resumed by `run_coding_agent`.

## Detached, and watched

A prompt is run the way the coding agent runs a task: started in a session of
its own (`setsid nohup`) with its events written to a file, and the platform
polls that file (`coding_agent/_task.py`). Two reasons. A prompt outlives the
sandbox service's ceiling for one command. And a person should see the
harness read, edit and run tests as it does them: each event becomes the
delegation frames the chat already draws (`coding_agent/_narration.py`,
`app.agents.subagent_events`), so the harness gets a panel of its own under
its own mark. A timed-out prompt, and a run that is cancelled, has its
process group stopped. Prompts in one toolset run one at a time, so two
prompts to the same session cannot interleave their stored session ids.

## Why one approval per prompt

A harness asks permission per file and per command when a person sits at its
terminal. Nobody does here, and forwarding each of those prompts through the
platform would make a person approve forty edits to accept one change. So the
platform asks once, before the prompt, when the approval is set, and the
harness runs under `--dangerously-skip-permissions` (Claude Code) or
`--dangerously-bypass-approvals-and-sandbox` (Codex) at `edit` access. The sandbox is the boundary: the
session runs in the agent's sandbox, whose filesystem the workspace already
governs, and a prompt's cost is booked on the run's ledger like any other
tool's.

## What it reuses

Everything the coding agent already proved, rather than a second
implementation of it: the CLI invocation and its stream parsers
(`coding_agent/_harness.py` - `invocation`, `claude_report`, `codex_report`),
the detached execution and its failure modes (`coding_agent/_task.py`), the
live narration (`coding_agent/_narration.py`), and the budget ledger
(`budget.py`). This package adds only the session files, the report with its
`kind` renamed, and the four tools.

## What it does not do yet

- A ChatGPT sign-in for Codex. The coding agent's sign-in flow - an isolated
  home, a visibility check, token rotation read back out of the sandbox - is
  not wired into this capability, so the picker offers API keys only. An
  OpenAI API key is what Codex runs on here.
- Run on a person's own computer. The session runs in the agent's sandbox;
  there is no `runs_on` setting, and no ACP session to a desktop app.
- Change what the harness may do mid-conversation. `access` is the binding's,
  fixed when the agent is published.
