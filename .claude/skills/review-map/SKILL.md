---
name: review-map
description: On-demand visual walkthrough of a pull request for a reviewer — projects the diff onto the system architecture map (changed components highlighted, before/after flows, suggested reading order) and publishes it as a private HTML artifact. Use when a diff is too large or system-touching to hold in your head while reviewing.
user-invocable: true
---

# Skill: Review Map

Turn a hard-to-hold-in-your-head pull request into a **private, visual walkthrough** so a
reviewer can grasp *what changed and how it moves through the system* before reading the diff
line by line.

This is a **per-reviewer comprehension aid**, not part of the PR record: the artifact is
private to whoever runs the skill and is meant to be discarded after the review. It changes
nothing in the repo or the PR. Contrast with `pr-description` (durable, for everyone) — this is
scaffolding for one review, today.

## Inputs

- **PR number** — optional. With one, review that PR (`gh pr diff <n>`, `gh pr view <n>`).
  Without one, review the current branch against **its own base**, which is not
  necessarily the repository default: a stacked branch targets its parent, and
  comparing it against `main` folds the parent's whole change into this walkthrough,
  corrupting the components, the risk and the reading order.

  ```bash
  BASE=$(gh pr view --json baseRefName -q .baseRefName 2>/dev/null) \
    || BASE=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name)
  git fetch origin "$BASE"
  git diff "origin/$BASE"...HEAD
  ```

## Steps

1. **Gather the change.** The diff, the commit log, the PR body if it exists, and the list of
   changed files with hunk locations.

2. **Locate it on the map.** Read `docs/architecture.md` (routes → services → repositories, DI,
   the request transaction, background dispatch) and the `mermaid` diagrams embedded in it.
   For a frontend-only diff, also check `docs/frontend.md`; for RAG/ingestion, `docs/rag-knowledge`
   topics via `docs/file-processing.md`. Identify which components (boxes) and interactions
   (edges) the diff touches. There is no separate ADR log in this repository — the closest
   record of *why* a boundary exists is `docs/about/design.md` ("the six decisions that shape
   the codebase") and the Hard boundaries section of `CLAUDE.md`; cite those where relevant
   instead of an ADR number. Prefer reusing the existing diagrams over inventing a new topology.

3. **Build the walkthrough as a self-contained HTML page**. Load the `artifact-design` skill
   first where the session has it; it comes from the host, not from this repository. It must
   contain, in this order:
   - **Changed components on the system map** — the architecture diagram with the boxes and
     edges this PR touches highlighted; everything else dimmed. Redraw the touched slice as
     inline SVG in the page (the source lives as a `mermaid` fence in `docs/architecture.md` —
     use it as the reference topology). The reader must see *"this PR lights up these parts of
     the system."*
   - **Before → after flows** for each changed interaction — a small side-by-side (or
     annotated) sketch of the sequence/topology as it was and as it becomes. The diagram in
     `docs/architecture.md` gives you the "before" to derive from.
   - **Suggested reading order** — the changed files grouped by layer (routes → services →
     repositories, or the frontend's data layer → store → component), ordered so the reviewer
     reads foundations before callers, with risky hunks flagged (a new permission gate, a
     transaction-boundary change, a spec/schema change, a migration, a vault/credential path)
     and a one-line "why read this next" per group.
   - **Anchors back to the code** — link each file/group to its path (and line where useful)
     and cite the governing rule under `.claude/rules/` or the hard boundary in `CLAUDE.md` it
     touches.

4. **Publish it** with the `Artifact` tool, where that tool is available to the session (it
   starts private). Hand the reviewer the URL and a two-line orientation: where the change
   lands on the map, and where to start reading.

   Neither the `Artifact` tool nor the `artifact-design` skill ships in this repository -
   both come from the host session - so a clean checkout has to be able to finish without
   them. Where they are absent, write the same page as a self-contained HTML file in the
   scratchpad directory (one file, inline CSS and inline SVG, no external requests) and hand
   over that path instead of a URL. The deliverable is the walkthrough, not the hosting.

## Rules

- **Accuracy over polish.** Every box you light up and every "before" you draw must match the
  actual code and the doc's diagram — a confident but wrong map is worse than no map. When the
  diff and a diagram disagree, say so: the diagram may be stale (worth flagging via
  `scripts/docs_drift.py` or a follow-up), or you may have misread the diff.
- **Reuse the doc's diagram.** Do not redraw the whole system; start from the `mermaid` diagram
  in `docs/architecture.md` (or the relevant topic page) and mark the delta.
- **Ephemeral and private.** Never post the artifact URL to the PR, commit it, or treat it as a
  deliverable. It is a lens for one reviewer.
- **Scale to the diff.** A small, single-layer PR may only need the reading order and one
  before/after; reserve the full map for genuinely large or cross-cutting changes (touching
  routes, services, repositories, and the frontend together, or a migration plus a spec change).
  If a diff is trivial, say so and skip the artifact rather than manufacturing one.
