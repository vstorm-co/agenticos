---
name: Runbook generator
description: Write a runbook somebody woken at 3am can follow without thinking.
category: devops
---

# Writing a runbook

Written for the least-context person on the rota, at the worst hour. Assume no
prior knowledge and no time.

## The shape

**Symptom** — what they will see, in the words the alert uses.
**Verify** — one command that confirms it is this and not something similar.
**Impact** — who is affected, so severity can be set immediately.
**Fix** — numbered steps, exact commands, expected output after each.
**If that fails** — the next branch, or who to wake.
**Afterwards** — what to check, what to record.

## Rules

Every command is copy-pasteable with placeholders in `<angle brackets>`. Every
destructive step says what it destroys and how to reverse it, immediately before
the command. Every step says how to tell it worked.

## Always name a person

An escalation to a team at 3am reaches nobody. Name the rota.

## Never

Write "investigate the logs" as a step, assume a tool is installed, or leave the
rollback in a different document.
