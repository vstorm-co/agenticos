# Workflows + Virtual Tables: implementation plan

Master plan for #56 and its thirteen delivery issues (#1781–#1793), covering
current status, the full dependency graph, the recommended build order, and
where each issue's design document lives. Rebuilt 2026-09-22 against the
milestone's live state; re-verify PR status and issue bodies before treating
any of this as current beyond that date.

Companion documents:

- [Shared contracts](56-shared-contracts.md) — the cross-cutting decisions
  (node contract shape, `expected_revision`, permissions) every design below
  is written against, so eleven separately-authored documents don't each
  invent their own answer.
- One design document per issue without a PR yet, named `<issue>-<slug>.md`
  in this directory, linked from its row below.

**Consistency pass, 2026-09-22.** The eleven design documents were written in
four dependency tiers so each later tier could read the finished output of
the tier before it; #1793, written last because it depends on all eight
others, was asked to actively surface any place two documents disagreed
about a shared mechanism rather than silently pick one. It found eight, all
now resolved directly in the affected documents (not just noted): a fourth
permission, `Perm.WORKFLOWS_RUN`, was missing from #1786 despite #1785 and
#1792 both needing it; #1788's `WorkflowRun` model was missing the four
causation columns #1785's cycle protection depends on; #1786's
`WorkflowVersion` had no field for the budget cap #1788 referenced; #1784's
node-surface operation key used a different format from #1788's canonical
`NodeAttempt.idempotency_key`; #1782's dependency-checker hook was never
registered against by any of #1783/#1784/#1785, the three features its own
docstring names as expected registrants; `Port` had no direction field;
`ScopeBoundary.body_node_ids`'s authorship (client vs. server) was left
unresolved by #1786 and inherited unresolved by #1790; and #1792 named its
own admission entry point two different ways in the same document. See
[#1793's design document](1793-e2e-acceptance.md#inconsistencies-found-while-writing-this)
for the original findings as #1793 wrote them, each now annotated with what
changed and where.

## Status

| Issue | Title | Status |
|---|---|---|
| #1781 | Evaluate Workflow Builder SDK | **PR #1813** (open). Decision: do not adopt the SDK, build on `@xyflow/react`. Cost estimate and recommendation recorded. Lab still on branch pending removal. |
| #1782 | Virtual Tables: typed storage | **PR #1812** (open). Built, three Codex review rounds, CI green, awaiting human approval and a `main` merge. |
| #1783 | Virtual Tables: UI and views | Not started. [Design](1783-table-ui-views.md). |
| #1784 | Virtual Tables: agent tools and typed nodes | Not started. [Design](1784-table-agent-tools.md). |
| #1785 | Trigger on table record created | Not started. [Design](1785-table-created-trigger.md). |
| #1786 | Workflow node contracts, registry, graph validation | Not started (planning only, no PR). [Design](1786-node-contracts.md). |
| #1787 | Workflows: visual editor | Not started. [Design](1787-visual-editor.md). |
| #1788 | Workflows: durable execution | Not started. [Design](1788-durable-execution.md). |
| #1789 | Workflows: core nodes | Not started. [Design](1789-core-nodes.md). |
| #1790 | Workflows: error routing and foreach | Not started. [Design](1790-error-foreach.md). |
| #1791 | Workflows: Python, files, images | Not started. [Design](1791-python-files-images.md). |
| #1792 | Workflows: channel adapters | Not started. [Design](1792-channel-adapters.md). |
| #1793 | End-to-end acceptance and docs | Not started. [Design](1793-e2e-acceptance.md). |

Verified 2026-09-22: `gh pr list --search "<N> in:body"` against every issue
in the milestone finds PRs referencing only #1781 and #1782. No other issue
in this range has an open or merged pull request.

## Dependency graph

Edges are "depends on", read from each issue's own `## Dependencies`
section (not inferred). #1781 and #1782 have none.

```
1781 ─┐
      ├─→ 1787
1786 ─┴─→ 1787
1786 ─→ 1788 ─┬─→ 1789
              ├─→ 1790 ─→ 1791
              ├─→ 1792 ─┐
              └─────────┴─→ 1785
1782 ─→ 1783
1782 ─┬─→ 1784
1786 ─┘
1782 ─┐
1788 ─┼─→ 1785
1792 ─┘

1793 ← 1783, 1784, 1785, 1787, 1789, 1790, 1791, 1792  (everything but 1781/1782/1786/1788 directly)
```

Full edge list, for anyone re-deriving this by hand:

| Issue | Depends on |
|---|---|
| #1781 | — |
| #1782 | — |
| #1783 | #1782 |
| #1784 | #1782, #1786 |
| #1785 | #1782, #1788, #1792 |
| #1786 | — |
| #1787 | #1781, #1786 |
| #1788 | #1786 |
| #1789 | #1786, #1788 |
| #1790 | #1786, #1788 |
| #1791 | #1786, #1788, #1790 |
| #1792 | #1786, #1788 |
| #1793 | #1783, #1784, #1785, #1787, #1789, #1790, #1791, #1792 |

## Build order

A topological sort of the table above, grouped into tiers. Everything in one
tier can be **built and reviewed in parallel** once every tier before it has
landed; nothing in a later tier can start correctly before its listed
dependencies exist, because each one either imports the prior issue's types
directly or its acceptance criteria assume the prior issue's behaviour.

| Tier | Issues | Why this tier |
|---|---|---|
| 0 | **#1781**, **#1782**, **#1786** | No dependencies. #1781 decides the editor engine for #1787. #1782 is the table foundation. #1786 is the workflow foundation — the node contract, the registry and graph validation every other workflow issue imports. |
| 1 | **#1783**, **#1787**, **#1788** | #1783 only needs #1782's service. #1787 needs #1781's decision and #1786's catalog/contract shape, but not execution. #1788 (durable execution) needs #1786's contracts to define what it runs. |
| 2 | **#1784**, **#1789**, **#1790**, **#1792** | #1784 needs #1782's service and #1786's registry. #1789/#1790/#1792 each need #1786's contracts and #1788's execution/waiting machinery to implement against. |
| 3 | **#1785**, **#1791** | #1785 needs #1782, #1788 *and* #1792 (the adapter that admits a run). #1791 needs #1786, #1788 *and* #1790 (its sandboxed nodes use the error/retry contract #1790 defines). |
| 4 | **#1793** | Closes the milestone: every other issue's acceptance criteria feed its four end-to-end journeys. |

Recommended **PR sequence** (one issue's branch stacked or merged before the
next tier starts, matching how #1782 and its follow-up #1823 were stacked in
practice):

1. **#1786** first, on its own. It is the highest-leverage issue in the
   whole milestone — #1784, #1787, #1788, #1789, #1790, #1791 and #1792 all
   import its types directly, and #1793 depends on all of those
   transitively. Every day #1786 is not merged is a day six other issues
   cannot correctly start.
2. **#1782 to merge next** (it is already built and reviewed; the work left
   is process, not design). #1783 and #1784's table half can start against
   #1782's *branch* before it merges — as #1786's earlier design already
   did — but #1793's table journeys need it actually merged.
3. **#1788** as soon as #1786 lands. It is the second-highest-leverage
   issue: #1789, #1790 and #1792 cannot be implemented for real (only
   designed) until it exists, because none of them have anywhere to run.
4. **#1783, #1787** can proceed in parallel with #1788, since neither needs
   execution — #1783 only needs #1782, #1787 only needs #1781 and #1786.
5. **#1784, #1789, #1790, #1792** once #1788 lands — these four can be
   built in parallel; they share no code with each other, only with #1786
   and #1788.
6. **#1791** once #1790 lands (needs its error/retry contract).
   **#1785** once #1792 lands (needs an adapter to admit the run) — these
   two can proceed in parallel with each other.
7. **#1793** last, closing the milestone.

This is a **planning target**, not a commitment — #56 already says the
1+3-week historical estimate needs re-validation for the expanded scope, and
nothing here overrides that.

## Cross-cutting risks

Carried from #1781's evaluation:

- **The editor cost is not fully estimated.** #1781's decision record puts
  the canvas chrome, palette and property panel at roughly 30/48/80
  engineer-days (best/likely/worst) on React Flow — about 6–16 weeks for
  #1787 alone, against a five-week milestone window, with the same owner
  also holding #1786, #1789 and #1790. #1787's own design refines this to
  roughly 49/78/129.5 days once its binding-field/picker/autosave/i18n scope
  is added on top. See that record's "Cost of building on React Flow"
  section before committing to a #1787 timeline.
- **#1786 will originate two platform-wide conventions**, not just a
  workflow feature: `expected_revision` optimistic concurrency (already
  proven on #1782's branch, so #1786 reuses rather than invents it — see
  [shared contracts](56-shared-contracts.md)) and `FileRef`, originated here
  rather than in #1791.
- **#1782 is unmerged.** Every design below that touches tables writes
  against #1782's *branch*, `feat/1782-virtual-tables-storage`, not `main`.
  Each such branch needs retargeting once #1782 merges, the same way
  #1823/PR #1828 already does.

Found while writing the individual designs:

- **#1784 proposes new dependency-injection surface**: a `run_auth:
  AuthContext` field on `AgentDeps` (an earlier draft also shared the run's
  own `db` session; the review rounds rejected that — each tool call opens
  its own short-lived session via `get_db_context()` instead, since sharing
  the run's session both reopens a transaction `CLAUDE.md`'s pre-model-call
  commit boundary exists to keep closed and hands an explicitly
  not-concurrency-safe object to code that can run concurrently), and an
  `operation_key` parameter on `VirtualTableService.create_table`. Neither
  exists today — no existing agent capability writes through a
  transactional service mid-run. `run_auth` still needs explicit sign-off
  before #1784 implementation starts, not just design review; it changes a
  type every capability depends on.
- **The public-API org-scoped key mechanism #1792's API adapter needs
  doesn't exist yet** in any design document in this milestone — #1792 and
  #1793 both name it as an external dependency rather than inventing a
  workaround. It is the same gap #1782's design left open for #1795/#150
  (owned by Kacper); #1786's `WORKFLOWS_RUN` permission and #1792's
  `WorkflowExposure` contract are ready for it once it lands, but the API
  adapter itself cannot be finished without it.
