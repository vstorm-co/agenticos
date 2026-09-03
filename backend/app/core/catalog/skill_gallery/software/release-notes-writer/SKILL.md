---
name: Release notes writer
description: Turn merged changes into notes a user can act on, grouped by what they mean.
category: content
---

# Writing release notes

The reader wants to know whether anything they use has changed. Sort for that.

## Group by consequence

**Breaking** first, always, with what to do about it · then new capability ·
then fixes, described by the symptom the reader saw rather than the code that
changed · then internal, briefly or not at all.

## Write from the outside

"Uploads over 10 MB failed silently" tells a user whether it affected them.
"Fixed a race in the ingestion worker" does not.

## Breaking changes

State what breaks, what to do, and by when. If a migration is needed, link it.
An unflagged breaking change is the fastest way to lose a self-hosting user.

## Always include

The version, the date, and the issue or PR number for anything a reader may need
to chase.

## Never

List every commit, use the commit subject as the note, or hide a behaviour
change under "improvements".
