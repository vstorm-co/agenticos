# workflows

Gives an agent the published workflows its binding names as tools:
`list_workflows` says which it may start and what input each asks for,
`run_workflow` starts one and waits for its answer, and `get_workflow_run` reads
a run that was still going when the wait ended.

Discovery includes the published `version_id` and effective Draft 2020-12
`input_schema`, alongside the existing simple `input` fields. Nested schemas
retain their local references, so callers inspect the contract admission uses.
The encoded discovery response is limited to 32 KiB even without optional tool
output limits. Larger responses are refused in full; narrow the binding or use
the HTTP input-schema endpoint outside the agent context.

A workflow is a reviewed, versioned process - a refund, a lead's follow-up, a
report - and this is how an agent hands one off instead of improvising the
steps. The agent decides when and with what; what happens is the graph.

- **As the member.** Each call rebuilds the member the run acts for from current
  membership and starts the run through `WorkflowExecutionService.start`, the
  API's own path: access, declared input, budgets and admission quotas hold, and
  the run is `triggered_by` `agent`.
- **Only what the binding names.** A workflow outside `workflow_ids` is refused
  before anything starts. It must be published to start by hand, by the API or
  by a workflow call.
- **No calls from inside a workflow.** An agent running as a workflow's step
  starts nothing: `workflow.run` calls another workflow and keeps the chain's
  loop and depth limits, which a tool call would bypass.
- **Waiting is bounded.** `wait_seconds` (5-300) caps how long a call waits; the
  run goes on regardless, and its id is handed back.

`run_workflow` is side-effecting, so a spec can require approval before it runs.
