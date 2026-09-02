---
name: Customer-facing postmortem
description: Explain an outage to customers honestly, without leaking internals or blaming a person.
category: content
---

# Writing a customer postmortem

Customers forgive outages. They do not forgive discovering it was worse than
they were told.

## The structure

What happened, in their terms · when it started and ended, in UTC with a local
note · who and what was affected, specifically · what caused it, honestly and
without internal detail · what was done · what changes so it does not recur,
with dates.

## Honesty rules

Say "we deployed a change that…" rather than "an issue occurred". Passive voice
reads as evasion. Never name an individual — the failure is the system's, and a
named engineer is a hostile act.

## Data

If data was lost, exposed or delayed, say so in the first paragraph. Burying it
turns an outage into an incident of trust, and it always surfaces.

## The commitments

Only what is already scheduled with an owner. A postmortem promise that does not
land is worse than not making it.

## Never

Overstate the fix, promise it cannot happen again, or publish before the
timeline is confirmed.
