---
name: code-review
description: How this organization reviews a change, and what a review must not let through.
category: engineering
---

# Reviewing a change

Read the whole change before commenting on any part of it. A review that
starts at the first diff hunk asks for things the third hunk already did.

## What a review is for

Correctness first, then clarity, then everything else. A comment about naming
on a change that corrupts data is a review that missed its job.

Say what is wrong and why it matters. "This is confusing" gives the author
nothing to act on; "this returns None when the list is empty, and the caller
indexes it" does.

## What must not pass

- A behaviour change with no test. Load `checklist.md` for the full list.
- A caught exception that is neither re-raised nor reported.
- A credential, token or key in the diff, including in a test fixture.
- A migration with no `downgrade`.

## How to say it

Distinguish what blocks from what does not. Prefix anything optional with
"nit:" so the author can tell in one pass which comments hold the merge.

When the fix is short, write it. A three-line suggestion is read; a paragraph
describing three lines is argued with.
