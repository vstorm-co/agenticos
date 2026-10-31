---
name: workflow-builder
description: Build and verify AgenticOS automations and API integrations, including tools unavailable in the MCP gallery.
category: automation
---

# Build a workflow around the job

A workflow is a published, repeatable graph of typed steps. Use it for explicit
sequences, event-driven jobs, branching, API integrations and auditable actions.
An agent handles conversation and judgment; a routine schedules an agent; a
workflow coordinates explicit steps. A workflow can call an agent for one decision.
Avoid creating all three when one solves the request.

## Discover, build, verify

1. Read `list_workflow_definitions` before making another automation. Inspect a
   match with `get_workflow_definition` and preserve its graph and revision.
2. Use `list_workflow_nodes`, then `get_workflow_node` for the steps needed.
   Inspect exact config/input schemas, port IDs, versions and resource references.
   Never invent a step, property, binding path, account, table or model ID.
3. Establish the event, input, actions and expected answer. Explain external
   effects plainly. Put operational records in a Virtual Table; retrieve prose
   from a knowledge base instead. Load virtual-tables when available.
4. Create a private draft. Build nodes with unique UUIDs, edges naming actual
   output/input ports and bindings naming the data passed between steps. Start
   with the smallest complete path. Save against `expected_revision`.
5. Test with agreed sample data. Test mode calls real APIs and can send messages
   or write records. Read the returned run with `get_workflow_execution`, then
   `get_workflow_execution_steps`. Queued does not mean succeeded. Check returned
   values, errors and the intended effects before declaring the automation ready.
6. Present the trigger and effects before publication. Publication freezes a
   version and activates its unattended triggers. A key cannot supply a retained
   human principal: if refused, direct the person to Publish in the console.
7. To make it an agent's tool, bind the AgenticOS platform MCP server
   (`account: platform`) and allow the workflow discovery, `run_workflow` and
   execution-reading tools it needs. Read its declared input first. MCP writes
   retain approval and run as the requesting member. Existing `workflows`
   capability bindings remain compatible with their resource grants; do not
   silently replace one with broader MCP access. A workflow's agent step must
   use a `workflow.run` node to call another workflow instead of starting a root.


## A service missing from the MCP gallery

A missing gallery entry does not mean the service is unavailable. First look for
an existing connected server. A custom MCP URL can be connected in the console.
For a documented HTTP API, a workflow with `http.request` can implement the action
and return a small typed result through `core.output`; an agent can then call that
workflow. Read the API's official documentation to verify the URL, method, request,
authentication, pagination and response shape. Use the deployment's existing vault
picker for credentials; never request or embed a raw token in chat, instructions,
a graph, a URL, a table, logs or a skill. Preserve the HTTP step's authorization,
egress and approval controls. A missing permission or connection is a concrete
setup step for the person, not a reason to invent a working integration.

## Reliability

Choose stable external IDs and idempotency keys for writes. Do not retry an action
whose effects may already have occurred without an idempotency contract. Bound
loops and API pages, handle expected failures explicitly, and choose budgets.
Keep resource access within the caller's organization. Read and reconcile revision
conflicts. Do not use another tool to bypass a refusal. Publish only after actual
verification, and name any verification the deployment could not perform.

A graph may have independent trigger roots. Keep existing starts when adding another; each run follows one reachable branch. Use one of each unattended kind. Shared steps must not read a different start's unavailable output. Test each entry using its `entry_node_id`, and explain that publication activates all configured unattended entries.
