---
name: pr-description
description: Create or update PR. Use this skill every time user asks to create or update a PR to ensure clear, consistent descriptions between PRs.
---

# Skill: PR Description

Create or update PR description based on git diff.

## Inputs

- **PR number** — required when updating an existing PR; provided by the user (referred to as `<pr-number>` below)
- **Base branch** — detect dynamically; do not assume `main`:
  ```bash
  BASE=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name)
  ```
  If the user names a different base (e.g. `develop`), use that instead.

## Steps

1. **Gather context**:
   - Refresh the base first: `git fetch origin "$BASE"`. `gh repo view` hands back a branch
     *name*; it does not update the local remote-tracking ref, and a stale `origin/$BASE`
     describes commits that merged upstream days ago as if they were this PR's.
   - For new PR: `git diff "origin/$BASE"...HEAD` and `git log "origin/$BASE"..HEAD --oneline`
   - For existing PR: `gh pr diff <pr-number>`, **and its current body**:
     `gh pr view <pr-number> --json title,body`. An update is a merge, not a rewrite: a body
     often carries hand-written limitations, verification evidence and issue links that the
     diff cannot reconstruct, and `--body-file` replaces all of it silently. Carry that
     content forward, and only rewrite what the diff has actually made wrong.

2. **Generate description** in this format:

```markdown
## Changes

### Summary

[Brief summary of changes - 1-3 sentences]

### Business Context

[Business/technical context - why was this change needed. Infer from branch name, commits, and code changes. Remove this section if unclear.]

### Changes

[Technical approach - main architectural decisions, main changes. Use bullet points.]

### Architecture

[Diagrams, for an architectural change only — see Rules. Reference each attached image as `![alt](./name.png)` with one sentence saying what the reader should take from it. Remove this section for a change with no architectural shape.]

### Verification

[Example queries, commands, or steps to verify the changes work correctly. When the change is observable through the project's own tracing/observability backend (new or changed spans, telemetry attributes, logged events — check whether the repo has one before assuming), include links or excerpts from example traces you actually produced — see Rules.]

### Linked Issues

[Link to any relevant issues or tickets found in branch name or commits. Remove this section if none found.]
```

3. **Execute** (write the body to a file and pass `--body-file`; a long body with backticks
   does not survive `--body "…"` intact):
   - New PR: `gh pr create --base "$BASE" --title "<title>" --body-file body.md`
   - Existing PR: `gh pr edit <pr-number> --body-file body.md`
   - Diagrams go in the body as mermaid, so there is nothing to upload and no asset URL to
     go stale. `gh` has no image-upload flag - `--attach` is not a flag `gh pr create` or
     `gh pr edit` has ever exposed - and a local PNG referenced by path renders as a broken
     image for every reviewer.

4. Return the PR URL.

## Rules

- No "Test plan" or "Generated with..." sections
- Keep descriptions concise
- Use present tense ("Add", "Update", "Remove")
- Omit `Business Context` and `Linked Issues` sections when there's nothing to fill in — don't leave placeholders
- **Include trace/log evidence for observable changes, when the repo has the means to produce it.** When the change produces or alters observability (new/changed spans, telemetry attributes, structured logs) and the project has a tracing or logging backend, link to or excerpt **example traces/log lines you actually produced** in the `Verification` section — one per meaningful path (happy path + key error paths), using that backend's own link format (e.g. a dashboard deep-link, a log query, a captured span tree). Only cite evidence you genuinely produced — never fabricate ids, URLs, or output. If the project has no such backend, or the change isn't observable through one, skip this and verify with the project's normal test/run commands instead.
- **Attach diagrams for an architectural change.** When a change adds or reshapes a flow
  across components — a new tool or service path, a new gate, a state machine, a
  cross-channel behaviour — put images in the `Architecture` section rather than making the
  reviewer rebuild the shape from the diff. Two usually suffice: one component/flow diagram
  (who calls what, and what each outcome writes) and one sequence diagram (the call order,
  with the refusal branches). Put the mermaid straight in the body, in a fenced ```mermaid
  block: GitHub renders it in a pull request description, so the diagram needs no renderer,
  no uploaded asset and no version of anything. It also stays readable in the diff and as
  text, which a PNG does not. A committed architecture doc's diagram belongs wherever this
  repo keeps those instead, e.g. `docs/architecture.md`, a `docs/architecture/` directory,
  or an ADR. Diagram the mechanism the PR actually changes, including its failure paths; a
  box-and-arrow restatement of the module tree earns nothing. Skip the section for a fix, a
  test-only change, or a one-file tweak.
