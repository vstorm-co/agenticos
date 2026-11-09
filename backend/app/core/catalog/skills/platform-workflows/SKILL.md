---
name: platform-workflows
description: "Design and verify AgenticOS workflow graphs, dependencies, bindings, entry points, API integrations and retries. Use for repeatable typed automation, including table events; discover node schemas before building."
category: automation
---

# Design a reliable execution graph

Use for nontrivial graph design, branching or integration failure analysis. The live MCP node catalog owns node types, ports, bindings, validation and execution parameters.

Define the input, observable output, entry point, execution identity and allowed effects. Reuse an existing workflow where it owns this responsibility. Prefer an agent for judgment and a routine for scheduling; combining all mechanisms is not a goal.

Use `get_workflow_input_schema` to inspect a published version's contract before calling it. Manual, API and Called by a workflow entries accept either simple `fields` or an `input_schema` in JSON Schema Draft 2020-12, with references local to that document. Nested input needs no user-defined Python model. Keep schemas on trigger config so publication and run admission use the same contract.

Trace whether every consumer can receive its producer's output on each entry path. Independent branches must not assume each other's values exist. Preserve existing entry points and test each affected route. Prevent a table-event workflow from repeatedly triggering itself on its own writes.

Design retries around external-effect identity. A timeout does not prove a send or write failed; inspect before retrying. Put credentials in their account/vault, and preserve network restrictions and approval gates. An unavailable integration is a concrete blocker, not a reason to fabricate a successful skeleton.

Use structural validation before a bounded test. Check the resulting records or remote effects as well as execution status. Publish only the reviewed behavior: publication can enable unattended entries. Explain which entries were checked, what changed, what is active and what still needs a person. Discover exact schemas as needed instead of loading a second API reference through a skill.
