---
name: agent-design
description: Turn "I need an agent for X" into a design - its one job, what it may do, what it knows, who approves.
category: product
---

# Designing an agent

Ask before building. One question at a time, with likely answers offered.

## Choose the workspace first

For ongoing research, writing, coding, a wiki or analysis across conversations,
propose Projects before designing a new agent. Read the Projects page in the
agenticos-guide skill. Reuse a relevant existing project, or create a private one
when asked, through approval. Shared files and instructions carry the work between
chats; full transcripts do not. A shared server workspace needs a service sandbox for code execution. Desktop
can instead use an approved local folder and local browser for the conversation,
without changing the agent spec. Ask where the work should happen; a local folder
is personal and is not shared by inviting people to the project. Mobile does not
supply a desktop execution environment.
A knowledge base complements the workspace when indexed retrieval is needed.
A one-off answer needs neither a project nor a new agent. Several related steps
in one continuing project do not by themselves require several agents.

## The questions

1. **What is the one job?** Split into specialists only when the jobs need different instructions, access or tools.
2. **Who talks to it?** Customers, a team, everyone - this decides where it is
   published (chat, website widget, Slack) and who may run it.
3. **What must it know?** Documents become a knowledge base; standing facts
   ("our office hours") become a context file; a repeatable procedure becomes a
   skill.
4. **What must it do?** Each action is a capability: searching the web, reading
   files and running code in a sandbox, drawing charts, publishing pages, calling
   a company tool through MCP.
5. **What needs a person's yes?** Anything that sends, changes or spends -
   e-mails, writes to a CRM, payments - waits for approval.
6. **What may it spend?** A monthly budget in dollars; start low.

## Shape the answer as

Name · one-line description · instructions (see the agent-instructions skill) ·
capabilities · knowledge · approvals · budget · where it is published. Then create
the draft and link the person to it in the Builder to try it before publishing.

## Prefer

Fewer capabilities over more: every tool is one more thing the model can get
wrong. Delegation to a specialist over one agent doing everything.
