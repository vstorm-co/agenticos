# Approval and per-tool presentation

Two things are decided finer than "is this capability on", and both key on a tool's
**stable id**.

## Why the id and not the name

A binding may rename a tool for its model. The approval gate matches on the name the
model actually called — resolved back from the id. Keying a stored decision on the
visible name instead would mean a rename silently removes the gate, and a
side-effecting call goes unattended with nothing reporting it.

The same applies to `tool_approval` and `tool_overrides` in a spec: both are keyed by
tool id. An id no such capability exposes is refused at publish, and so is a name no
model could call (`TOOL_NAME_PATTERN` — `[a-zA-Z0-9_-]{1,64}`).

## How approval resolves

Most-specific first, in `app/agents/capabilities/approval/_policy.py`:

1. `tool_approval[<tool_id>]` in the binding — `required` or `never`
2. `approval` on the binding — the default for every tool it contributes
3. the capability's `side_effecting` flag

`"default"` at levels 1 and 2 means "fall through". The Builder states the outcome in
words rather than describing the rule, because a rule the reader has to run in their
head is a setting nobody dares touch.

`approval_required_tools(spec)` turns all of that into a set of tool *names*, once,
while the agent is assembled. The gate consults that set on every call. Keeping the
rule in one place means no surface re-derives it and gets a different answer.

## What the gate guarantees

From `capabilities/approval/_capability.py` — the gate wraps *tool execution* rather
than living inside a tool, for the same reason the budget guard wraps model requests:
enforcement a tool has to remember to call is enforcement a new tool will forget.

- **The approved arguments are what runs.** A decision is granted against the
  arguments a person read. On replay the gate executes those, not whatever the model
  proposes the second time round.
- **No channel means no.** An agent running somewhere nobody can be asked — a
  schedule, a webhook — refuses the call and says so.
- **A refusal is an answer, not a crash.** Both a rejection and a missing channel
  come back to the model as tool output.

## What is *not* gated

**MCP tools.** `approval_required_tools` iterates `spec.capabilities` only. MCP
server tools are discovered at run time, so nothing declared them and nothing gates
them. Do not assume otherwise when reviewing a change that adds an MCP connection to
a published agent.

## Presentation overrides

```python
tool_overrides={"search_documents": ToolOverride(
    name="search_refund_policy",
    description="Look up what our refund policy says about this order.",
)}
```

Both fields are prompt surface. Neither can reach the tool's identity.

A field nobody set is **absent** from the serialised spec rather than stored as
`null`: "explicitly no name" is not a state this can be in, and a stored `null` made
a reverted field look permanently overridden in the Builder.

`ToolOverrides` (in `_overrides.py`) wraps a capability only when something is
actually overridden, which keeps the common agent exactly what it was.

## Splitting a capability

If a new tool has side effects and the existing ones do not, the capability is now
two decisions wearing one name. Prefer a second capability. `side_effecting` is per
capability, and per-tool `approval` in a spec is a way for an *agent author* to be
stricter than the default — not a substitute for declaring the truth in code.
