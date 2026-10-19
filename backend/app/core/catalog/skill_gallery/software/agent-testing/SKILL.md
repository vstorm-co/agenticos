---
name: agent-testing
description: Try an agent before publishing it - the questions to ask, the failures to look for, what to change.
category: qa
---

# Testing an agent before it goes live

Publish only after ten real questions, asked the way real users ask them.

## Ask

- Three ordinary questions it must answer well.
- Two it should refuse or hand to a person - check it does, politely.
- Two whose answer is not in its knowledge - it must say it does not know.
- One in another language, one with a typo, one rude.
- One that tries to make it ignore its instructions.

## Look for

Made-up facts (check every answer against the source it cites), answers that are
too long, a tool used when it should not be, an action that should have waited
for approval.

## Where to ask them

In AgenticOS, **Test** in the Builder opens a chat beside it that answers as the
unpublished draft - nothing has to be published to try it. Pin the ten questions
there and rerun them after every change. Once a version is live, **Compare** puts
the draft beside it and asks both the same question, so the difference you see
is the change you made. Every test turn is a run, budgeted and marked `test` in
Activity.

## Fix one thing at a time

A wrong fact - the knowledge base. A wrong tone or scope - the instructions. A
wrong action - the capability or its approval. Ask the same question again after
each change.
