# Background tools

Lets the agent send a slow tool to the background and keep working: it is told
the tool has started, answers or works on the rest of the request, and gets the
result as a message when it arrives. Built on `BackgroundTools` from
pydantic-ai-harness. Contributes no tools.

## Which tools

The ones their own capability marks with `BACKGROUND` (`metadata` of
`{"background": "optional"}`) - today `browse_web`. The model decides per call,
through a `run_in_background` argument added to that tool's schema: a browse it
needs the answer of before it can say anything is better waited for. An agent
author decides only whether the agent may do this at all, by binding the
capability.

## What it keeps

- **Screening.** The library delivers a background result past the
  tool-result hooks. This subclass runs the agent's `after_tool_execute` hooks on
  it itself - guardrails, tool output limits - so a page the agent read in the
  background is redacted and cut exactly as one read in the foreground is.
- **Approval.** The approval gate sits outside it, so a gated tool parks for its
  approval before anything runs in the background.
- **Budget.** A background task runs inside the run, under the same ledger: what
  it spends is the run's.
- **Cancellation.** Stopping the run cancels every background tool still going.

## What it does not do

- A run that parks - an approval, a question - cancels its unfinished background
  tools; their results are not delivered after the resume.
- It runs nothing after the run ends. A background tool is not a job queue.
