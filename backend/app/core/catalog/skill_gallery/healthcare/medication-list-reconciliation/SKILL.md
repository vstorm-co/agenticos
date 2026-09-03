---
name: Medication list reconciliation
description: Compare medication lists from two sources and surface every discrepancy for a pharmacist.
category: operations
---

# Reconciling medication lists

This produces a list of differences for a person to resolve. It never resolves
them.

## Compare and classify

Line up the lists from both sources and put every difference in one of four
buckets:

- **Only in A** — possibly stopped, possibly missed on transcription.
- **Only in B** — possibly started, possibly a duplicate under another name.
- **Different dose, route or frequency.**
- **Same drug, different name** — generic against brand. Say both names.

## Present it as a table

One row per discrepancy, with the value from each source and which bucket it is
in. Sorted with dose differences first, because they are the ones that harm.

## Add without being asked

Any pair that is the same drug class appearing twice, and anything on the list
that the record shows as a documented allergy.

## Never

Decide which list is correct, suggest a dose, or drop a discrepancy because it
looks like a typing error. Every difference goes to the pharmacist.
