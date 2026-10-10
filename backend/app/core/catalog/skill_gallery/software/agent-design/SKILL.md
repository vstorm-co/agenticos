---
name: agent-design
description: Turn "I need an agent for X" into a design - its one job, what it may do, what it knows, who approves.
category: product
---

# Designing an agent

Ask before building. One question at a time, with likely answers offered.

## The questions

1. **What is the one job?** If the answer has "and" in it, propose two agents.
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
