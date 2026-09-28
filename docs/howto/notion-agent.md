---
title: "Search and update Notion from an agent"
description: "Connect Notion as an MCP server, let an agent answer from a page it finds itself, and require a person's review before it appends anything."
---

# Search and update Notion from an agent

Connect Notion through [MCP](../mcp.md) so an agent can search a workspace, answer from what it finds, and append meeting notes to a page - with a person deciding, each time, whether the write actually happens. This page describes both workflows and the exact connection choices they depend on. It is not runnable here: this environment has no Notion account to connect, so there is no recorded run below.

## What you need

- A [running installation](../install.md) with a model profile.
- **`connections:manage`** to add Notion for the whole organization, or nothing beyond an ordinary member account to connect it for yourself only, under **MCP servers → You**.
- A Notion workspace you may authorize an OAuth app against.

## Connect Notion

Notion is in the catalog under **oauth**, `https://mcp.notion.com/mcp` (see [the catalog](../mcp.md#communication-support-knowledge)). Two decisions matter before an agent ever touches it:

**Organization or personal.** Adding it under **MCP servers → Organization** (`connections:manage`) makes one Notion connection answer for every agent bound to it, on every surface, under one shared name and identity in Notion's own audit log. Adding it under **MCP servers → You** instead means each person connects their own workspace access, and a binding to *each person's own account* (`account: personal` in the spec) has the agent speak to Notion as whoever is asking - Notion's own log says who did what, but a colleague who has not connected their own Notion gets a message telling them to, not an answer from someone else's. See [whose account a binding speaks through](../mcp.md#whose-account-a-binding-speaks-through).

**A name and a tool prefix.** Connecting a second Notion workspace forces a second name - the prefix `notion` is taken, so the second one becomes `notion-2`, and the model reads whichever prefix its binding names. See [two names, and they answer different questions](../mcp.md#two-names-and-they-answer-different-questions).

For a small team pointed at one shared workspace, the organization's account is the simpler start; switch to each person's own account when different people should only reach what their own Notion login can see.

## Build the agent

1. Create an agent in **Agents → New agent** and select your model profile.
2. In **Toolbox**, add the Notion server under **MCP servers**, bound to the organization's account (or each person's own). Leave its tools unrestricted for a first pass, or narrow `allowed_tools` on the binding to a search/read tool only if this agent should never write.
3. Set the instructions below, then **Publish**.

```text
You answer questions from this organization's Notion workspace.
Search before you answer, and open the page you found before quoting it.
Cite the page's title in your answer, and say plainly if nothing in Notion answers the question.
When asked to add meeting notes to a page, find the exact page first, show the person what you are about to append, and only write it once they confirm.
```

The model reaches Notion's tools under the connection's prefix - `notion_search` and whatever else the last probe found, prefixed the same way. Which tools exist at all is decided when the connection is probed, not written into the spec by hand; see [which tools, and who decides](../mcp.md#which-tools-and-who-decides).

## Workflow: find a page and answer from it

Ask a question the workspace should answer, in a fresh conversation:

```text
Who owns the Q3 onboarding checklist, and where does it live?
```

The model calls a search tool, opens the page that looks right, and answers with the page's title as its citation. If nothing matches, the instructions above ask it to say so rather than guess - check that refusal the same way you would check a correct answer, in a knowledge-search agent's own trial.

## Workflow: append meeting notes, with a person deciding

This is the workflow worth being exact about, because **MCP tools carry no per-tool approval of their own** - the Builder says so directly: *"MCP tools are outside the approval gate entirely: an approval set on a capability does not cover them, so anything these servers can do, this agent can do without asking."* A write binding you can name in the spec, like `execute` or `send_email`, has a `required`/`never`/`default` switch; a Notion write tool discovered at connection time never gets one, because nothing declared it in code. See [what MCP does not get you](../mcp.md#what-mcp-does-not-get-you).

The gate that does reach it is the conversation's own. Before asking the agent to write, whoever is talking to it opens **Chat controls → Approval mode** and chooses **Ask about everything** - a session setting that "reaches further than the spec's gate on purpose, to the tools no capability owns" (see [how much one conversation wants to be asked](../governance.md#how-much-one-conversation-wants-to-be-asked)). With that set:

```text
Append these notes to the Q3 onboarding checklist page: attendees Ana and Marek, decided to move the kickoff to Monday, action item for Marek to update the calendar invite.
```

The write tool now parks the same way `execute` does in [the CSV chart trial](csv-chart.md#run-it): the chat shows **Tool approval required** with the exact page and content the model is about to send, and a person reads it before choosing **Approve**. Skip **Ask about everything** and the same write runs immediately, with nothing to review - so an agent bound to a write-capable Notion connection is only as reviewed as the mode the person talking to it happened to choose that turn.

## Check the result

| Check | Reference |
| --- | --- |
| A question Notion answers | Cites the page title, and the answer matches what the page says |
| A question nothing in the workspace answers | Says so, rather than inventing a plausible-sounding page |
| An append, with **Ask about everything** off | Runs immediately - confirm this is what you want before it happens |
| An append, with **Ask about everything** on | Parks as **Tool approval required**, showing the exact page and text |
| Rejecting the parked write | The page is not changed, and the agent can relay the refusal rather than crashing |
| Someone with no personal Notion connection, on a personal-account binding | Told to connect one, not answered from somebody else's workspace |

## When it goes wrong

- **The agent has no Notion tools at all.** The connection has never been probed successfully - open **MCP servers**, run the check, and confirm it shows a tool list before binding it to an agent.
- **A write runs with nobody reviewing it.** Check the conversation's own **Approval mode** - `required` on a capability does not reach an MCP tool, so a write connection needs the session set to **Ask about everything** every time review matters.
- **Two Notion connections collide under one name.** Rename one - see [name collisions](../mcp.md#name-collisions) for what a run does when it cannot tell them apart.
- **A colleague gets "connect your account" instead of an answer.** Expected on a personal-account binding until they connect their own Notion under **MCP servers → You**.

## Record the trial

Keep the question and its citation, the connection's scope (organization or personal) and which Notion workspace it points at, and every approved or rejected write with the page it targeted. A person still decides who may bind a write-capable Notion connection to an agent, and reviews every append that mode did not park for review on its own.

## Next steps

For the same review question against a project tracker instead of a document, see [turning meeting notes into tasks](meeting-to-tasks.md). For narrowing what an entire organization's Notion connection may do before any agent binds it, see [which tools, and who decides](../mcp.md#which-tools-and-who-decides).
