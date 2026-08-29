---
name: Architecture decision record
description: Capture a decision, the options rejected, and the cost accepted.
category: documentation
---

# Writing an ADR

The value is not the decision. It is the reasoning, read in two years by
somebody about to undo it.

## Five sections

**Context** — what forced a decision now, including constraints.
**Options** — every one seriously considered, including doing nothing.
**Decision** — what was chosen, in one sentence.
**Consequences** — what this costs, what it makes harder, what it rules out.
**Status** — proposed, accepted, superseded, with dates.

## The section people skip

**Consequences.** An ADR listing only benefits is a sales pitch, and it is
useless to the reader trying to work out whether the trade still holds.

## Write the rejected options fairly

The next reader will reconsider one of them. If it is described as a straw man,
they will assume it was never properly examined and redo the work.

## Never

Write it after the fact to justify a decision, leave the date off, or edit a
superseded ADR in place — supersede it with a new one that links back.
