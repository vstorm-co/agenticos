---
title: "Turn meeting action items into tasks with approval"
description: "Have an agent propose one tracker task per real action item from a meeting transcript, and require a person to approve each one before it is created."
---

# Turn meeting action items into tasks with approval

Give an agent a meeting transcript's action items and a [Linear or Jira MCP connection](../mcp.md#project-management), and have it propose one task per item rather than create anything unattended. The person reading the proposals edits or rejects before a single task lands in the tracker. This page is not runnable end to end here: this environment has no Linear or Jira connection, so there is no recorded run below.

## What you need

- A [running installation](../install.md) with a model profile.
- **`connections:manage`** to add Linear or Jira as an organization-wide MCP connection, or an ordinary member account to connect one for yourself under **MCP servers → You**.
- A meeting transcript to work from. [Summarising a meeting](meeting-summary.md) covers checking the decisions and action items in one before any of them becomes a task.

## Prepare the input

A small, invented transcript with one clear action item, one action item missing a due date, and one raised concern that nobody actually owns - the last is the edge case worth checking:

```text
Weekly ops sync - 24 September 2026
Attendees: Priya, Tom, Sana

- Priya will update the onboarding doc with the new pricing tiers by Friday.
- Tom will follow up with the vendor about the delayed shipment.
- Sana raised that the support queue is growing, but nobody was assigned to look into it.
```

Reference: two real action items (Priya, due Friday; Tom, no due date stated) and one open question with no owner, which is not an action item.

## Connect the tracker

Linear is in the catalog under **oauth**, `https://mcp.linear.app/sse`; Jira and Confluence share one entry, also **oauth**, at `https://mcp.atlassian.com/v1/sse` (see [the catalog](../mcp.md#project-management)). For a tracker the whole team files into, connect it under **MCP servers → Organization** so every bound agent creates tasks as the same integration identity; bind [each person's own account](../mcp.md#whose-account-a-binding-speaks-through) instead only if your tracker expects tasks to be filed as whoever asked for them.

On the connection, narrow `allowed_tools` to the create/comment tool this workflow needs, if the server also offers ones that edit or delete existing issues - the binding can only narrow within what the connection already allows, never add back what it excludes.

## Build the agent

1. Create an agent in **Agents → New agent** and select your model profile.
2. In **Toolbox**, add the tracker under **MCP servers**.
3. Set the instructions below, then **Publish**.

```text
You turn meeting notes into tracker tasks.
Propose one task per real action item: a title, the assignee named in the notes, a due date only if one was actually stated, and a one-line description.
Do not invent an assignee, a due date or a priority that the notes do not state.
If something was raised but nobody was assigned to it, say so as an open question rather than proposing a task for it.
Create each proposed task with its own tool call, one at a time, so each can be reviewed on its own.
```

## Run it

Before asking the agent to create anything, open **Chat controls → Approval mode** and choose **Ask about everything**. This matters here for the same reason it matters for [appending to Notion](notion-agent.md#workflow-append-meeting-notes-with-a-person-deciding): the tracker's create tool is discovered from the MCP connection at run time, so no per-tool approval declared in the spec ever reaches it - the session's own approval mode is the only gate a create call gets.

```text
Turn the action items in this transcript into tasks:

Weekly ops sync - 24 September 2026
Attendees: Priya, Tom, Sana

- Priya will update the onboarding doc with the new pricing tiers by Friday.
- Tom will follow up with the vendor about the delayed shipment.
- Sana raised that the support queue is growing, but nobody was assigned to look into it.
```

Each create call parks on its own - a model that proposes two tasks in one step parks two separate approval rows, each decided independently. Read the exact title, assignee and due date on each one before choosing **Approve** or rejecting it; a rejected call is relayed back to the agent as a refusal it can act on, not a crash.

## Check the result

| Check | Reference |
| --- | --- |
| Number of tasks proposed | Two - one per real action item |
| Priya's task | Assignee Priya, due Friday |
| Tom's task | Assignee Tom, no due date invented |
| Sana's item | Not proposed as a task; named as an open question with no owner |
| Rejecting one proposed task | The tracker does not receive it; the agent's final reply says which one was skipped |
| Approving the rest | The tracker receives exactly the approved tasks, nothing more |
| The same transcript with **Ask about everything** off | Every proposed task is created immediately, with nothing to review first |
| A transcript with no action items at all | Says there is nothing to turn into a task, rather than inventing one |

## When it goes wrong

- **A task is created before anyone reviewed it.** Check the conversation's **Approval mode** first - `required` on a capability never reaches an MCP tool, so review depends on the session being set to **Ask about everything**, every time.
- **The agent invents a due date or an assignee.** Tighten the instructions rather than the connection - this is a prompting failure, and the transcript should already have told it what it does not know.
- **A raised concern becomes a task anyway.** Check the instructions distinguish "assigned to someone" from "mentioned" - the fixture's open question exists to catch exactly this.
- **Two different agents both propose a task for the same action item.** The tracker itself is the source of truth here, not this platform's run history - check the tracker for a duplicate before assuming the agent is wrong.

## Record the trial

Keep the transcript, every proposed task, which were approved or rejected, and the tracker's own state afterward - AgenticOS's approval log records what was proposed and who decided, not whether the tracker still looks that way later. A person still reads every proposal, corrects a wrong assignee before approving rather than after, and decides who may bind a create-capable tracker connection to an agent at all.

## Next steps

For the same approve-before-write pattern against a document instead of a tracker, see [searching and updating Notion](notion-agent.md). To check a transcript's decisions and action items before turning any into tasks, see [summarising a meeting](meeting-summary.md).
