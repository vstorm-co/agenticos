# Issue triage

Read when filing or updating AgenticOS issues. Current user instructions take
precedence over these repository conventions.

## Record confirmed defects

Fix in-scope defects in the current change; a separate issue is unnecessary. For
out-of-scope defects, check existing issues before filing. Describe the failure,
reproduction steps, relevant code location and how to verify a fix. Distinguish
confirmed bugs from suspicions and state whether the current change introduced
the problem or merely discovered it.

## Board fields

Use existing repository metadata; retrieve current values rather than copying
old milestone names or opaque IDs from examples.

| Field | Convention |
|---|---|
| Labels | One kind (`bug`, `enhancement`, `documentation`, `dependencies`, `ci`, `meta`), `severity:*` for bugs, `effort:*`, and `frontend` / `security` when applicable |
| Type | `Bug`, `Feature` or `Task` |
| Project | `VstormOS`, not the cross-repository `Vstorm OSS` board |
| Milestone | Inherit from the related issue where appropriate; otherwise the current week's milestone unless work belongs later |
| Status | `Backlog` for newly filed work; `In progress` only when work has started |

When filing a defect found while working on another issue, inherit its project,
milestone and `priority:*` where appropriate. Link that issue in the body.
Check installed CLI options or use the GitHub API for unsupported fields; do not
claim that metadata was set when an update failed.

## Relationships

The repository uses #168 as its issue map. Read it before filing, check for
duplicates and related clusters, and update the relevant cluster when adding an
issue. Link related work or state that none was found after checking. Make blockers
visible from the blocked work too.

Use a sufficient result limit or pagination when examining the backlog. Absence
from a partial listing is not evidence that an issue is closed.

Close issues only when fully resolved. For a partial contribution to a batch issue,
update its relevant checkbox and leave it open.
