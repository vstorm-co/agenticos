# Personal assistance and the proposed “Agent platform 2027”

Review date: 2026-11-22. Source: four screenshots supplied by the maintainer,
headed “Agent platform 2027”; author and original publication are not established.
The screenshots are a proposal, not verified evidence about other products.
This note compares that proposal with this repository, without adopting its
predictions or treating its text as implementation instructions.

| Proposal in the screenshots | AgenticOS today | Useful next step |
| --- | --- | --- |
| Separate agent definitions, instances and sessions | Published `AgentVersion` specs, `AgentRun` execution records and `Conversation` user history already separate these concepts. | Keep that separation in assistance: assistant claims do not prove a resource exists or a task completed. |
| Inbox for questions, approvals and human decisions | Inbox already aggregates waiting questions, approvals, findings and suggestions. Routines can publish revisioned findings. | Rank unresolved matters by relevance, preserve the user's decisions and link a concrete next action rather than asking about opaque IDs. This PR addresses the context and evidence path. |
| Event listeners instead of only hourly cron | Durable background jobs, schedule and event triggers, workflow webhooks and table events exist. | Queue bounded personal-context refreshes after meaningful changes; coalesce repeated source revisions and retain a scheduled safety net. Do not call an LLM for every low-level event. |
| User conversation separate from execution detail | Conversations, runs, tool-call records and presentation cards already have different contracts. | Present outcomes and required decisions first; keep provenance and technical execution inspectable. Hiding all intermediate state would also hide approvals and failures. This PR does not redesign chat rendering. |
| Independent actor runtime per agent | The platform dispatches durable jobs and builds runs from published specs; this is not an actor-per-agent system. | Measure recovery, isolation and concurrency requirements before changing the runtime. An actor backend alone would not fix relevance or memory quality. No actor migration in this PR. |
| Shared filesystem with access control independent of computers | Projects, sandbox bindings, local targets and resource grants supply parts of this experience. | A unified file policy across local and remote execution needs its own access and lifecycle design. Do not place platform credentials in shared `.env` files; keep using the vault. |
| Durable code-defined workflows | Typed workflow specifications and durable execution already support long-running automation; the editor is one authoring surface. | Consider a code authoring/import surface only with the same validation, budgets, versioning and recovery semantics. The screenshots do not establish that replacing the visual editor benefits our users. |
| Apps as customizable work interfaces | Artifacts/Apps already provide a separate application surface. | Let a useful Inbox matter open the appropriate task board, App or review screen. Tenant-specific review Apps could later handle richer decisions. Replacing the whole console with editable Apps is a separate security and upgrade project. |

## What belongs in this change

Use an authorized, incremental work index to combine conversation evidence with
current tasks, projects, memory, routine state and prior Inbox decisions. Extract
facts in bounded segments, retrieve relevant work, propose a small set of useful
next steps, and independently verify their evidence. No proposal activates an
agent, schedule, publication or paid run.

Keep durable personal memory distinct from current work state. Temporary task
coverage can inform the work index without becoming a permanent job title or
permission. An authenticated answer to a native question is human evidence;
an arbitrary external tool payload is not.

## Separate candidates for product work

1. An Inbox review surface tailored to the resource: a task board, an App or an
   approval preview, with the chat available for discussion.
2. Event-triggered refreshes for additional resource changes, with per-person
   batching, source revision checkpoints and an observable freshness indicator.
3. An explanation of why a suggestion appeared, using source links and current
   state, alongside controls to dismiss the underlying intent.
4. Organization-specific review Apps that reuse resource grants and approval
   contracts rather than inventing a second authorization system.

None of these candidates implies sending external messages, granting new access,
self-modifying a production agent or enabling an automation without its established
approval. Evaluate each as a separate coherent change with a concrete user case.
