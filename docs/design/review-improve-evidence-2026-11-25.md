# Improve evidence integration review — 2026-11-25

This release-train slice integrates the selected changes from these non-draft
pull requests without importing their unselected feature-branch parents:

| Pull request | Reviewed head | Result |
| --- | --- | --- |
| #3446 | `c1bb5fe77bc43328f74b4bddba9bd37ddbf4e1df` | Pin the holdout share on each Improve session and repair skill test sets. |
| #3445 | `428c5f79d7007272358e736c451f815ef40f11d2` | Warn about hidden characters in structured field changes before JSON serialization. |
| #3440 | `0272b313678a3758cd93a29e39e27a3ef71c31d7` | Show the dataset's Improve guidance and its organization-local attribution before starting. |

## Necessary prerequisites and review fixes

The target train lacked the hidden-character helper and complete binding diff.
Only those supporting changes were taken for #3445: added and removed bindings
show their bodies, control/format characters are written out, and structured keys
and values are inspected before serialization. An astral format-character case
covers code points outside the basic multilingual plane.

The target train also allowed dataset helper instructions to replace platform
instructions. Selected guidance-composition changes from
`cf322b04036f9e98fd13918b3b234bd859091445` retain the platform rules and append
explicitly subordinate dataset guidance. Model calls and their estimates use the
same composition. The helper editor distinguishes editable guidance from
read-only platform rules. This does not import the parent approval or broader
evidence-filtering features.

The holdout share is carried through the already prepared `Inputs` snapshot,
without a second dataset read or an assertion on a concurrently deleted dataset.
A regression changes the dataset between input preparation and persistence and
verifies that the session retains its prepared share. Later attempts also retain
the session's pinned value.

Guidance authorship is server-owned. Dataset reads omit the author's internal ID;
estimates resolve a display name only for a currently active member of the same
organization, with neither email nor cross-organization identity disclosed.
Forged client authorship cannot replace that metadata. A separate UI heading ID
is generated per guidance section.

## Migration and rollout

`backend/alembic/versions/0366_improvement_holdout_share.py` keeps the source
revision identifier but follows this train's `0370_console_role_presentation`.
The final train must join migration heads if another slice adds a revision.
Existing sessions are backfilled from their dataset's current share, because the
historical value was never recorded; orphan sessions use 0.5. Skill datasets are
repaired to a share of one and all their cases become held out. Downgrade removes
the new session column and intentionally retains those repairs.

The new column is non-null without a misleading fixed default. Pause API
admission and workers during migration, then restart updated processes; old
processes must not insert sessions after the migration. This is not a rolling
upgrade compatibility claim.

## Verification

- Scoped backend batch: 72 tests passed across helper settings, Improve pipeline,
  Improve rounds, guidance composition and migration SQL.
- Prepared-share regression batch after the input-snapshot refinement: two
  passed, 13 deselected.
- Final frontend batch: 77 tests passed across diff views, field changes, helper settings,
  dataset guidance, start-session integration and hidden characters. The two new
  UI/helper modules and both diff components have 100% statement, branch,
  function and line coverage.
- Backend `ty`, frontend `tsc --noEmit`, documentation translation freshness,
  generated Architect-guide consistency and the strict four-language MkDocs build
  passed. Alembic upgraded an empty scratch pgvector database, passed drift check,
  downgraded one revision, upgraded again and passed the second drift check.
- Full application suites, coverage gates, build and end-to-end checks are
  reserved for CI at the final combined commit; no paid model calls were made.

A pre-existing security-test inventory failure in the parent train concerns its
portability and chat-cost tests, not this slice. The parent integration owns that
repair before final CI.

## Visual evidence

Desktop and mobile before/after captures render the real diff component and the
new guidance component with synthetic data. Each capture is visibly labelled
“Component preview · synthetic data · no model execution”. The surrounding
selection/cost shell is a deterministic harness, not evidence of a full live
Improve session or a paid model run. The temporary preview route was removed.

Capture files are kept outside the repository:

- `/private/tmp/agenticos-improve-before-desktop.png`
- `/private/tmp/agenticos-improve-after-desktop.png`
- `/private/tmp/agenticos-improve-before-mobile.png`
- `/private/tmp/agenticos-improve-after-mobile.png`
