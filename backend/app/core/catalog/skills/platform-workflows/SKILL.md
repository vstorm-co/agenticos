---
name: platform-workflows
description: "Design and verify AgenticOS workflow graphs, dependencies, bindings, entry points, API integrations and retries. Use for repeatable typed automation, including table events; discover node schemas before building."
category: automation
---

# Build the graph from its contracts

Use a workflow for a repeatable sequence, branching, event handling or an explicit
API integration. Use an agent for judgment, a routine to run that agent later,
and a table for durable state. A workflow may contain an agent step; creating a
workflow, agent, watch and routine together is rarely necessary.

1. Search existing definitions and inspect a match before creating another.
2. Describe inputs, output, entry point, identity, side effects and failure policy.
3. Call `list_workflow_nodes` and `get_workflow_node` for the actual schemas and
   ports of every node type. The deployment's catalog is the authority.
4. Build the complete graph with real UUIDs and explicit data bindings. Submit it
   with `prepare_workflow_draft`, optionally with its private table, rather than
   many partially connected writes. Editing uses the revision actually read.
5. Run `check_workflow_draft` for structural validation without executing actions.
6. Test the agreed entry with `test_workflow_draft`, then read both execution and
   step results. Verify resulting records or remote objects, not only run status.
7. Publish only the behavior the person approved. Publication can activate every
   configured unattended entry; a structural check does not activate anything.

## Dependencies that need deliberate design

| Boundary | Required decision |
| --- | --- |
| A step consumes another step's output | The producer must be reachable on this entry and supply the bound type |
| Multiple starts in one graph | Preserve existing starts; test each `entry_node_id` separately |
| Two independent branches | Do not bind one to unavailable outputs from the other |
| An agent calls another workflow | Inspect the callable workflow's input contract and permission |
| A workflow invokes another workflow | Use the catalog's workflow-run node; avoid recursive root execution |
| A table event writes its own table | Filter meaningful state transitions to avoid feedback loops |
| A schema changes | Read the current schema/version and inspect dependent bindings before editing |
| Retry after a timeout | First check whether the external effect already happened; use its stable idempotency identity |

Create missing integrations only from verified official API documentation. Put
credentials in account/vault configuration and reference their IDs; never inline
them in HTTP nodes, URLs, graph data or Context. Keep network and approval policy.
If a service lacks an MCP server but has a suitable API, an HTTP workflow can
provide the bounded operation. Do not weaken policy to make a failed test pass.

A missing account, environment or permission is a blocker with a setup link, not
a successful skeleton. “Output step succeeded” does not verify delivery, sending
or a schedule. Return the draft link, tested entries, evidence for intended
effects, remaining blockers and whether the workflow is published. Load the
existing `workflow-builder` skill for additional integration recipes when bound.
