---
name: platform-skills
description: "Create and improve reusable AgenticOS skills from a procedure or successful chat. Write accurate triggers, progressive references, acceptance cases and tool boundaries; save and bind the skill without confusing it with memory or permissions."
category: engineering
---

# Teach the next agent a procedure

A skill is reusable know-how, not a transcript, a fact store or a new permission.
Use it for repeatable work with important choices and checks. Put standing facts
in Context, preferences and decisions in Memory, large reference corpora in
Knowledge, and outstanding commitments in Tasks.

Search existing skills before creating one. If the request comes from a previous
chat, read the authorized conversation and tool results: extract the successful
procedure and the mistakes it corrected. Remove case-specific people, figures,
credentials, private correspondence and output documents unless explicitly needed
as an appropriate, permissioned example. A skill attached widely is read widely.

## Write for selection and execution

Use a stable lowercase-hyphenated name that does not collide with a capability.
The description is the selection rule: say what it achieves and concrete requests
that should load it. Distinguish neighboring skills. The Markdown body contains:

1. The job and when a simpler approach is sufficient.
2. Inputs and prerequisites the agent must inspect, not assume.
3. The sequence, with decision points and exact current tool contracts.
4. What to do on missing data, permission refusal, conflicts or partial failure.
5. Verification and the deliverable the person can inspect.

Keep the first screen useful. Put long examples, templates and reference tables
in named resources and reference them directly from the body. The runtime lists
names/descriptions before loading bodies through `load_capability`; resource
text is read with `read_skill_resource`. Do not invent a `load_skill` tool.
Resources are text files here; a binary deck belongs in output storage, not a
text skill resource. Read a script before writing it into a workspace and running
it. A skill's example command does not establish that its dependencies exist.

For example, a supplier-report skill selects only for supplier status reviews,
queries the actual table, distinguishes unknown from late, produces blockers,
dates and next actions, and verifies each cited record. Its example uses labeled
fictional data. It does not hard-code one customer's IDs or claim mail access.

## Save, bind and evaluate

Use platform `create_skill` for a new procedure or update the existing skill when
the corresponding tool is available. Add resources through the supported skill
resource tools or the skill editor; do not claim a local file is installed in
the platform. Read the resulting skill and attach its ID in the agent draft,
preserving other skill IDs. Saving a skill alone does not bind it to every agent.
Test in a draft with an ordinary request, an ambiguous near-match that should not
load it, a missing prerequisite and a hostile source instruction. Check outputs
and tool effects, then repair the procedure. Publish the agent only when authorized.

Return the skill link, intended agents, checks performed and remaining limits.
Do not silently overwrite organization-specific edits with a shipped example.
