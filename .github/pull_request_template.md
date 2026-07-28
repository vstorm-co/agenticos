## What this changes

<!-- One paragraph. What behaviour is different after this merges? -->

## Why this way

<!-- The decision, not the diff. What else did you consider, and why not that?
     This is the part reviewers cannot reconstruct from the code. -->

## Checks

- [ ] Tests cover the new behaviour, and would fail without the change
- [ ] `make check` passes (lint, format, types)
- [ ] Platform-layer coverage is still 100%
- [ ] If a capability was added or changed, its `README.md` says why
- [ ] If a migration was added, `alembic downgrade base && alembic upgrade head` works

## Notes for the reviewer

<!-- Anything you are unsure about, or deliberately left out. -->
