# Table access hardening

Status: claimed implementation draft. Owner: shermzy.
Requested on 15 November 2026 (Asia/Singapore). Base: t3 at 080c1294.

## Problem

Linked labels and computed values are filtered by destination access, but raw
link UUID arrays can survive in record responses. CSV can fall back to those
arrays when the destination table is inaccessible. Invalid stored row policies
currently become an unrestricted policy.

## Implementation contract

- Derive public link IDs, labels, lookups and rollups from one authorized set.
- Export an empty visible link set without falling back to stored UUIDs.
- Fail closed on invalid stored policies and permit an authorized repair.
- Preserve unreadable existing relationships when a legacy client replaces its
  visible list; never write a sanitized response back as the complete record.
- Keep revisions, idempotency receipts, history, outbox events and tenant checks.
- Keep stored records complete internally; response projection is per caller.

## Verification

Cover full serialized responses, CSV fallback, invalid policies, projected
linked reads, harmless updates with hidden links, and unauthorized link writes.
Run focused backend tests and the exact revision's CI. Use no production data.

## Series and ownership

This is the first change in the claimed tables series. Follow-ups are row
Read/Write access (#99), link deltas (#100), normalized relationships (#101)
and database isolation (#102). Coordinate through this PR before overlapping
edits. Implementation starts after all drafts and claims are published.
