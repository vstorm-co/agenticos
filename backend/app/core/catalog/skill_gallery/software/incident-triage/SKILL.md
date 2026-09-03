---
name: Incident triage
description: Turn an alert into a severity, an owner and a first hypothesis within minutes.
category: devops
---

# Triaging an incident

The first five minutes decide the length of the incident. Establish blast radius
before cause.

## Answer four questions, in this order

1. **Who is affected** — all users, one tenant, one region, one endpoint?
2. **What is broken** — unavailable, slow, or wrong answers? Wrong answers are
   worse than down and are usually noticed later.
3. **Since when** — and what shipped or changed in the hour before it.
4. **Is it getting worse?**

## Set severity from impact, never from cause

An unknown cause is not a reason to hold severity down. Say the severity, the
reason for it, and who owns it now. One name, not a team.

## First hypothesis

Name the most recent change touching the failing path, and say how to disprove
it in under five minutes. A hypothesis nobody can test quickly is a distraction.

## Always post

What is known, what is not, what is being tried, and the next update time. A
missed update time costs more trust than the outage.

## Never

Speculate about cause in a customer-facing channel, or close before the
follow-ups have owners.
