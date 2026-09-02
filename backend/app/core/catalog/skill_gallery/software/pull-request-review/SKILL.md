---
name: Pull request review
description: Review a diff against the repository's own conventions, in the order a maintainer does.
category: engineering
---

# Reviewing a pull request

Read the surrounding code before the diff. Most real problems are in what the
change assumes, not in what it says.

## In this order

1. **Does it do what it claims** — and does the description match the diff?
2. **The failure paths** — errors, empty results, concurrency, partial writes.
3. **Tests** — does one fail without the fix? A test that passes on the old code
   tests nothing.
4. **Conventions** — the repository's, not your preferences.
5. **Blast radius** — what else calls this, and does the change hold for them?

## Say why, and how sure

Distinguish "this is a bug, here is the input that breaks it" from "I would have
done this differently". Both are worth saying; conflating them wastes the
author's time.

## Always sweep the siblings

If the change touches one of several similar call sites, check the others. The
same defect is usually in all of them.

## Never

Block on style a formatter should own, or approve a diff you did not understand
because the author is senior.
