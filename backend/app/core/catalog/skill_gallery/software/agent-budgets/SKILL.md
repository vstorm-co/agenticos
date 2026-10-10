---
name: agent-budgets
description: Set an agent's monthly budget and limits so a mistake costs little and a busy month does not stop it.
category: operations
---

# Budgets and limits

## Set a budget from an estimate

Messages per day × days × cost per message, rounded up by half. Read the agent's
past spend first when it has any. A new agent: start at a few dollars a month and
raise it after a week of real use.

## What each limit protects

- **Monthly budget** - the agent stops answering when it is reached; nothing
  surprises the invoice.
- **Per-run limits** (tokens, tool calls) - one runaway conversation cannot burn
  the month.
- **Approvals** - an action that costs money or reaches a customer waits for a
  person.

## When it runs out

Say who sees the alert and how to raise it: the agent's Limits in the Builder.
A budget hit is the platform working, not a failure.
