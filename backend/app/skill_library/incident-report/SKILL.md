---
name: incident-report
description: How to write up an incident so the next person can act on it, not just read it.
---

# Writing an incident report

An incident report is written for somebody who was not there, reading it under
time pressure, six months later. Everything below follows from that.

## Order

Impact first. Who was affected, for how long, and what they could not do. A
report that opens with architecture makes the reader work to find out whether
it matters.

Then the timeline: what happened, in order, with times. Then the cause. Then
what is being changed.

## Rules

**Times are absolute and in UTC.** "Twenty minutes later" forces the reader to
do arithmetic while comparing two reports.

**Name systems, not people.** "The deploy job did not wait for the migration"
is actionable. "Marek deployed too early" is not, and it makes the next person
quieter about their own mistakes.

**Separate what is known from what is believed.** Write "we think" where it is
a theory. A report that reads as certain and is wrong is worse than one that
says which part is a guess.

**Every action item has an owner and a date**, or it is not an action item —
it is a wish. Load `template.md` for the structure to fill in.

## What not to do

Do not write "human error" as a cause. It is where the investigation stops
being useful: a system that a tired person can break at 3am is the finding.
