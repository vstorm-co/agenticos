---
name: vstorm-code-review
argument-hint: '[model]'
description: High-signal, convergent code review for any repository. Runs a staged pipeline of subagents (Scope → Correctness → Security → Quality → Verification → Judge), one dedicated subagent per angle, all grading against one shared finding taxonomy, so every candidate is raised, filed, or refuted with proof — never silently re-surfaced after a fix. Accepts an optional `model` argument (default Claude Opus 4.8) that every subagent runs on. Use to review a pull request (first review) or to re-review code that was already reviewed and fixed. Run only after merge conflicts are resolved.
---

# Skill: Code Review standard

> This document is the specification for the Claude Code **code-review skill**.
> The skill runs a multi-stage pipeline of subagents (§3); every stage shares the
> one finding taxonomy in §2, which is injected into each subagent.

## 0. Invocation & arguments

The skill takes one optional argument: the model every subagent in the pipeline
runs on. It arrives through `$ARGUMENTS`, which is the substitution Claude Code
actually performs — a frontmatter key does not create a named `$model` variable,
so a body written against one is read as the literal text `$model` and the
caller's override is silently lost.

- **The argument** — when the caller passes nothing, `$ARGUMENTS` is empty; treat
  empty as the default **`claude-opus-4-8`** (Claude Opus 4.8). The orchestrator
  spawns every finder, the Verification stage, and the Judge on this model, so the
  whole pipeline grades on one model unless the caller overrides it (e.g.
  `claude-sonnet-4-5` for a cheaper pass). Orchestration and the per-stage fan-out
  are specified in §3.4.

**Resolved model for this run:** the first whitespace-separated token of
`$ARGUMENTS` — if empty, use `claude-opus-4-8` (Claude Opus 4.8), spawned via the
Agent tool's `opus` tier (§3.4). A caller override maps to its own tier (e.g.
`claude-sonnet-4-5` → `sonnet`).

## 1. Purpose & when to run

Automated code reviews tend to produce noise — they surface many irrelevant
issues, and they keep finding new "issues" regardless of how many fixes were
made. This skill exists to make automated review **high-signal and convergent**:
every candidate is raised, filed, or refuted with proof — never silently
re-surfaced after a fix.

- The review runs as a staged pipeline of subagents (§3), all grading against one
  shared taxonomy (§2).
- **Run a review only after merge conflicts are resolved.**
- The pipeline runs in one of two **modes** (§3.3): a **first review** of a pull
  request, or a **re-review** of code that was already reviewed and fixed.

## 2. Shared taxonomy — the finding contract

Every finding produced by any stage is classified on four axes — **severity**
(§2.1), **commonality** (§2.2), **origin** (§2.3), **type** (§2.4) — and carries a
**verification status** (§2.6) and a **destination** (§2.7). This taxonomy is the
contract shared by every subagent: it is injected into each finder's prompt, and
the orchestrator grades every finding against it (§3.2). It is self-contained — no
stage needs anything below §2 to classify a finding.

### 2.1 Severity: `blocking` · `major` · `minor` · `nitpick`

Severity is the impact of the issue **when it occurs**, independent of how often
it occurs (frequency is commonality, §2.2). Judge severity by consequence — a rare
defect with catastrophic impact is still `blocking`.

- `blocking` — **un-waivable**: the PR cannot be merged and no one may knowingly
  accept it — the merge gate refuses. Judge it blocking when, on occurrence, it
  delivers silently-wrong results, loses or corrupts data, breaches another
  principal, or kills a core shared path. For security it means sensitive data
  leakage, e.g. access to another user's private data. A blocking finding holds
  the hard gate only once `verified` (§2.6); while `unverified` it behaves as
  `major`.
- `major` — **must-fix, but waivable**: a maintainer may consciously ship it with
  an explicit, tracked accept-risk decision (a `dismissed` finding, §3.3); absent
  that waiver it blocks merge. Judge it major when the harm is bounded, visible,
  and recoverable — it fails loudly, is retryable, leaves no persistent bad state,
  or sits off the core path. For security it means access to information that
  doesn't directly compromise other users, e.g. an existence oracle for an object
  with a given `id`.
- `minor` — when it occurs, the feature still works but is not perfect; worth
  improving before merge, but the PR can be merged. For security it means exposure
  of information that should not be public but harms no one.
- `nitpick` — negligible impact: polish or preference. Batched, never blocks (see
  §2.7).

### 2.2 Commonality: `common` · `rare` · `negligible`

Commonality is how often the issue actually occurs in real use; the criteria below
are aids — when they disagree, judge by expected frequency. Commonality is
informational context for prioritisation and reviewer attention; it does not by
itself gate merge. See §2.7 for the only commonality values that affect routing.

- `common` — the issue is likely to come up in normal use: it occurs on the main
  execution path, or triggers on realistic non-default input or configuration.
  - a single plausible condition is enough — no rare coincidence required;
  - expected to occur within normal usage volume.
- `rare` — the issue is unlikely to come up.
  - needs an uncommon combination of inputs or configuration;
  - several atypical conditions must coincide, or a narrow timing window / specific
    race, or a deprecated / seldom-exercised code path;
  - occurs only occasionally across many runs.
- `negligible` — the issue virtually doesn't occur. This kind of issue should never
  be raised.
  - requires inputs or state the interface does not actually allow;
  - cannot be reached without changing the code, interface, or deployment;
  - depends on an environment that does not occur in practice.

### 2.3 Origin: `introduced` · `pre-existing`

- `introduced` — the issue was introduced in this PR.
- `pre-existing` — the issue exists in the base branch.

A pre-existing defect that this PR first puts on a live path — newly **exposed** or
materially worsened by the change — is classified `introduced`: it is raised on the
PR and its severity gates merge like any introduced finding. Note in the finding
that the underlying code predates the PR.

### 2.4 Type: `correctness` · `performance` · `style` · `security`

- `correctness` — the feature does not behave as expected; there's a bug in the
  logic.
- `performance` — the algorithm could be more optimal, i.e. faster.
- `style` — anti-patterns are present, code style is not in line with the rest of
  the repository or the official guidelines, or code/comments are too verbose.
- `security` — the feature introduces a security issue.

### 2.5 Report root causes, not downstream symptoms

For every potential finding, trace the observed failure back to the earliest
defect introduced by the pull request that must be changed to resolve it.

Create **one** finding when both conditions below are met:

- multiple failures result from the same underlying defect, **and**
- correcting that defect would resolve all of those failures.

Describe the root cause as the finding's title and primary problem. List the
resulting symptoms, affected flows, and consequences as supporting impact rather
than separate findings.

Create **separate** findings when any of the conditions below are met:

- they require different fixes,
- they occur independently of one another, **or**
- one would remain after the other defect was corrected.

**Fold vs. split — the rule of thumb:** fold when one fix resolves all; split when
they need different fixes. So fold multiple *symptoms of one root cause* into a
single finding, but keep *genuinely distinct defects on the same line* separate —
e.g. an authorization check that is both a `security` bypass and a `correctness`
wrong-branch is two findings, because each needs its own fix.

Place the review comment on the line that introduced the root cause whenever
possible. If that line is not part of the diff, comment on the closest relevant
changed line and clearly identify the actual source. Do not group findings merely
because they appear in the same feature, file, or execution path.

Example: if one incorrect authorization check exposes several endpoints, report the
faulty check once and list the affected endpoints. If two endpoints contain
independent authorization mistakes requiring separate changes, report them
separately.

### 2.6 Verification: `verified` · `unverified` — and the refuted bar

Every finding carries a **verification status** — `verified` or `unverified` —
orthogonal to its severity, commonality, origin, and type. Any severity may be
`unverified`.

- **`verified`** — existence shown by concrete evidence: a runtime reproduction, a
  failing script or test, a captured log/trace, or an **airtight static trace that
  names the exact input and the exact line where it fails**. Prefer evidence for
  `blocking` and `major` findings. If a change-verification skill is present, run a
  regression check on core user flows (first reviews and re-reviews alike). Collect
  logs/traces (e.g. Logfire) and attach them to ground the finding.
- **`unverified`** — general reasoning or a plausible-but-unpinned code path. Still
  raise it; mark it `unverified` and suggest how the contributor can confirm it.

**Only a `verified` finding gates merge.** An `unverified` finding is always
raised, but never holds the hard merge gate — an `unverified` `blocking` finding
behaves as `major` (raised, waivable, §2.1) until evidence promotes it. This keeps
a possibly-hallucinated blocker from freezing a merge.

**The refuted bar — when a candidate may be discarded.** A candidate may be
**discarded** only when it is provably false from the code:

- (a) **factually wrong** — quote the contradicting line;
- (b) **impossible** — a type, constant, or invariant forbids the state; show it;
- (c) **already guarded in this diff** — cite the guard.

If you cannot meet that bar, **do not discard** — raise it `unverified`. Who may
discard is defined in §3.2 (finders never delete; Verification and the Judge hold
discard authority).

**Never dropped — stays unverified.** These realistic-but-unpinned classes survive
to a raised finding rather than being discarded: concurrency races; nil/undefined
on a cold-cache or error path; falsy-zero treated as missing; off-by-one on a
boundary the code does not exclude; retry/partial-failure; a regex or allowlist
that lost its anchor.

### 2.7 Destination: `raise` · `GitHub issue` · `none`

Every finding routes to exactly one destination. Use the first rule that matches:

1. The finding is `negligible` → **none**. A `nitpick` → **batched summary
   comment**: collect all nitpicks from the round into one optional comment; never
   raised individually, never blocks merge. The batched summary is advisory —
   nitpicks carry no fix-or-dismiss obligation and may be silently skipped.
2. The finding is `pre-existing` (§2.3):
   - **unrelated to the PR's change** → **fast-track to GitHub issue**: file it as
     an issue proposal and do **not** raise it on the PR; it never enters the
     raise / re-raise / fix-or-dismiss loop (a pre-existing defect the PR *exposes*
     is reclassified `introduced` per §2.3, not this);
   - if it is `blocking` (§2.1) and the feature cannot function until it is fixed →
     **raise**;
   - otherwise, if it is valid — not `nitpick`, `negligible`, or `unverified` →
     **GitHub issue**;
   - otherwise → **none**.
3. The finding is `introduced` (§2.3) → **raise**. If it is `minor` and still
   unfixed at merge, convert it to a **GitHub issue** — unless it is `unverified`,
   which is never filed as an issue and stays a raised comment. Commonality is not
   a severity: `rare` describes how often the path is taken, and a rare data-loss
   or cross-tenant defect is still `blocking` and still unwaivable (§2.1), so it
   stays on the merge gate rather than becoming an issue somebody reads later.

Verification (§2.6) is orthogonal: a finding may be raised while `unverified`, but
an `unverified` finding is never filed as a GitHub issue.

> **⚠️ Who files GitHub issues.** The review skill only *proposes* a `GitHub issue`
> destination in its output — it does **not** open or close issues itself. Until a
> dedicated issue-filing skill exists (§5), a **human files** the issue from the
> proposal. Review agents never create or close GitHub issues autonomously.

### 2.8 Report format

Use a unified template for every finding, so contributors get a consistent layout:

```markdown
### [SEVERITY | COMMONALITY | ORIGIN | TYPE] Short imperative title · `RR-a3f2`

**Location:** `path/to/file.py:L120-L134` (root cause)
**Verification:** verified | unverified
**Destination:** review comment | GitHub Issue | none
**Status:** open | fixed | dismissed | refuted   (machine-readable; re-review reads this)

**Root cause:**
One or two sentences naming the underlying defect — not the symptom.

**Symptoms:**
- Observable failure 1 (`path/to/other_file.py:L45`)
- Observable failure 2

**Evidence:** (provide for blocking/major when practical; if unavailable, mark the finding unverified)
Repro steps, failing input, or trace excerpt (e.g. Logfire trace ID / log lines).

**Suggested fix:** (optional, one sentence or a short diff)
```

## 3. The pipeline

The skill runs as a sequence of subagent **stages**. A human reviewer performs the
same stages in order. Each finder returns candidate findings; the orchestrator
collects and grades them (§3.2); Verification challenges them; the Judge produces
the final review.

### 3.1 Stages

| Stage | Kind | Responsibility |
|-------|------|----------------|
| Scope | setup | Establish the PR objective, acceptance criteria, changed behavior, blast radius, relevant files, review mode, and evidence plan (§4.1). |
| Correctness | finder | Functional correctness, regressions, state transitions, errors, and contracts (§4.2). |
| Security | finder | Changed trust boundaries, authorization, unsafe input paths, and sensitive-data exposure (§4.3). |
| Quality | finder | Established repository patterns, reuse, maintainability, and clear efficiency regressions (§4.4). |
| Verification | challenge | Challenge each candidate; verify its execution path, scope, origin, and evidence; apply the refuted bar (§4.5). |
| Judge | synthesis | Trace root causes, deduplicate, assign labels, route, filter noise, and produce the final review (§4.6). |

### 3.2 Collecting and grading, and who may discard

The orchestrator spawns the finders, **collects every finding they return, and
grades each against the §2 taxonomy** (severity, commonality, origin, type) before
handing the graded set to Verification and the Judge.

**Finders never delete a candidate.** A finder that is confident a candidate is
provably false (by the refuted bar, §2.6) forwards it tagged `self-refuted` with
the cited evidence rather than dropping it. **Discard authority belongs to
Verification and the Judge** — they apply the refuted bar and route `negligible` →
none. Nothing dies silently, so every discard is auditable. Every review stamps the
reviewed commit SHA it ran against, and every raised finding carries a stable ID
and status line (§2.8); together these are the **ledger** a re-review (§3.3)
reconciles against.

### 3.3 Modes: first review and re-review

**First review** — run the full pipeline over the pull request diff, per §4.

A finding is a **durable object**, not a fresh emission each round. Every *raised*
finding carries a **stable ID** (`RR-xxxx`) and a machine-readable **status line**
(§2.8), both stamped into its posted comment — the PR comments *are* the ledger.
Every review also stamps the **reviewed commit SHA** it ran against, machine-findably,
so a later re-review anchors to it. Lifecycle: `open` → `fixed` (verified resolved)
/ `refuted` (§2.6) / `dismissed` (human closure); a `fixed` or `dismissed` finding
can reopen via regression, a symptom-only fix, or the high-severity carve-out.

**Re-review** — for a pull request that was already reviewed and fixed:

- **Baseline.** Anchor to the reviewed commit SHA stamped in the most recent
  review — not a fuzzy "last review." Read all existing review bodies, inline
  comments, and finding status lines first to reconstruct the ledger.
- **Scope — reconcile, don't re-scan.** Focus on the diff since the baseline SHA —
  do not re-run the whole pipeline over the entire PR. Still read callers and
  dependencies when correctness requires it (§4.2); the diff alone is not always
  enough to judge a change.
- **Reconcile each prior finding against the current code.** Correctly fixed →
  `fixed`, post a one-line resolution note, stop raising. Symptom-only (violating
  root-cause, §2.5) or unfixed → stays `open`, **re-raised** and routed through
  §2.7 — re-raising is not a "new" issue. Now provably false (§2.6) → `refuted`.
- **Dismissal — how a human closes a finding.** A human may close a finding
  through **any** attributable channel: a **threaded reply** on its comment,
  **resolving its thread**, or a **top-level comment naming its ID**. The signal
  must map to a specific finding ID — a bare global comment with no ID is ignored.
  A `/dismiss <reason>` keyword is unambiguous; free-text is classified
  **conservatively** — only a clear dismissal counts, otherwise the finding stays
  `open`. A **resolved thread** is closure: re-review checks the code and records
  `fixed` if the defect is gone, else `dismissed` (human override). Every
  dismissal is logged with its source (channel, author, reason) — an auditable
  transition, never a silent disappearance.
- **No ignoring.** Every raised finding must terminate in **fixed** or
  **dismissed**. Re-review never auto-demotes, auto-drops, or ages out an open
  finding — it re-raises it every round, at full severity, until the developer
  acts, and an open finding keeps its merge-gate weight. **Nitpicks are the sole
  exception**: they are the batched advisory summary (§2.7), carry no
  fix-or-dismiss obligation, and may be silently skipped.
- **New defects.** Raise **any defect introduced in commits after the baseline**,
  not only regressions of existing behavior — fresh code in a fix commit can
  introduce brand-new bugs.
- **High-severity carve-out.** A `blocking` or `major` `correctness`/`security`
  defect may **always** be raised — and **reopens a dismissed finding** — once it
  becomes `verified`, even one an earlier pass missed in the original diff. First
  passes miss things, and a missed or wrongly-dismissed blocker must never become
  permanently unraiseable.

### 3.4 Orchestration — one subagent per stage, finders in parallel

Every stage in §3.1 runs as its **own dedicated subagent**. Never fold two angles
into one agent, and never let the orchestrator do a finder's work inline — each
angle gets an isolated context so one lens cannot crowd out another, and each
finding is attributable to the stage that raised it.

- The three finders — **Correctness (§4.2), Security (§4.3), Quality (§4.4)** — are
  independent and run **in parallel**: spawn all three as separate subagents in a
  single batch, then wait for every one to return before proceeding.
- **Verification (§4.5)** runs as one subagent **after** all finders return. It owns
  evidence *execution* and must run serially (§4.5), so it never overlaps the
  finders — that is why the finders only propose repro recipes and never run
  servers themselves.
- **Judge (§4.6)** runs last, as one subagent, over the verified set.
- **Scope (§4.1)** runs first, as one subagent, and its output (objective,
  conventions, mode) is injected into every finder.
- **Force the model on every spawn.** Each subagent is spawned through the Agent
  tool with its `model` field set **explicitly** — never left to inherit. The Agent
  tool's `model` takes a tier alias (`opus`, `sonnet`, `haiku`, `fable`), so map the
  resolved model (§0) to its tier and pass it. With no caller override the resolved
  model is Claude Opus 4.8, so **pass `opus` on every spawn** — Scope, all three
  finders, Verification, and Judge alike. Never inherit and never downgrade a stage
  to a different tier.

## 4. Per-stage instructions

### 4.1 Scope

Establish the pull request's main objective. It is defined either in the issue
tracker (e.g. JIRA) under the ticket the PR is tagged with (e.g. `[ABC-123]`) or in
the PR description on GitHub. Derive the acceptance criteria, the changed behavior, the relevant files,
and the review mode (first review or re-review). The finders focus heavily on this
objective.

**Assess stakes and blast radius.** Identify affected principals and shared paths,
irreversible or externally visible side effects, security/data/financial impact,
recoverability, and whether the code is a throwaway prototype or production path.
Use the repository's ADRs and domain docs to find declared one-way doors and
non-waivable invariants. Turn that assessment into an evidence plan: concentrate
finder attention and stronger verification on the highest-impact paths, while
keeping routine changes proportionate. Low stakes reduce the amount of evidence
needed; they do not make a known correctness or security defect acceptable.

**Build the design contract before reading line by line.** For a non-trivial
change, summarize the idea the implementation must preserve: goal and non-goals,
domain concepts, invariants, state transitions, ownership/trust boundaries,
failure and recovery behavior, and any material performance assumptions. Cite the
issue, PR, ADR, contract, domain glossary, or architecture document that governs
each part; identify assumptions that exist only in the PR or code. Inject this
compact contract into every finder so they review one shared mental model. Keep it
proportionate: a mechanical, low-risk change does not need a new design document.

**Check canonical-document coherence.** Compare architectural or domain changes
with the repository's canonical sources (for example `CONTEXT.md`, ADRs, contracts,
and architecture documents). When the PR introduces, reverses, or materially
changes an invariant or design decision, verify that the owning document changes
with it or that the PR explains why no durable update is needed. A code/document
mismatch that changes expected behavior is a `correctness` candidate; absent
documentation alone is an advisory, not a merge blocker.

**Gather the governing conventions.** Locate the root `CLAUDE.md` and the
`CLAUDE.md` in each modified directory, plus the §5 footgun list they point to, and
inject them into every finder's prompt — so all finders share one copy and each
`style` finding cites the codified rule it violates (§4.4) instead of rediscovering
it per-finder. If a project security checklist exists at
`.claude/claude-security-guidance.md` (the same file the `security-guidance` plugin
reads), load it too and inject it into the Security finder (§4.3), so in-session
review and PR review grade against one shared threat model.

### 4.2 Correctness finder (and regressions)

Determine whether the change implements the intended behavior for the main flow and
realistic alternative flows without breaking existing functionality.

- **Establish the expected behavior.** Derive it from the objective, acceptance
  criteria, Scope's design contract, documented contracts, existing tests, and
  established repository behavior. First test whether the overall model is
  coherent, then inspect the implementation points that realize its invariants;
  do not assume either prose or code is correct when they disagree. Do not report
  a difference from the reviewer's preferred design as a bug. If the intended
  behavior is ambiguous, state the assumption and mark the finding `unverified`
  unless stronger evidence exists.
- **Trace the complete behavior.** For each requirement, follow the execution path
  from input to observable result: how inputs are validated and transformed; which
  branches decide behavior; which state is read or changed; which internal/external
  operations are invoked; how failures are handled; and what output or side effect
  is produced. Review callers and dependencies when necessary — do not judge a
  function only in isolation.
- **Check state, inputs, and failure paths.** Verify that state transitions begin
  from valid states and preserve invariants; related state changes stay consistent;
  partial failures do not leave invalid state; repeated execution does not cause
  unintended duplicate effects; missing, empty, malformed, boundary, duplicate, or
  stale inputs behave correctly; and early returns, fallbacks, retries, defaults,
  and exception handlers do not hide failures or fake success. Prioritize realistic
  conditions allowed by the interface.
- **Check contracts.** At component boundaries, verify agreement on inputs,
  outputs, errors, optional values, formats, and completion semantics.
- **Wrapper / proxy / adapter routing.** When the PR adds or changes a type that
  wraps another (cache, proxy, decorator, adapter, read-through store): verify
  every method routes to the **wrapped instance**, not back through a shared
  registry/session/store — re-entering the front instead of the backing store
  causes recursion, cache re-entry, or an id reused across a still-running entry.
  Verify it forwards every method its callers actually use.
- **Deletions pass.** For every line the PR **deletes or replaces**, name the
  invariant or guard it enforced, then locate where the new code re-establishes it.
  If you can't find it, that's a candidate — a dropped guard, a narrowed
  validation, a removed error path, or a deleted test that covered a real case.
- **Regressions.** Identify existing flows that share the changed code, data,
  configuration, interfaces, or side effects, and determine whether behavior
  changes. Do not raise speculative regressions merely because shared code was
  touched — explain the specific affected flow and the conditions under which it
  fails. Do not start servers or Docker yourself; hand the Verification stage a
  repro recipe to run (§4.5). Until it runs, mark the finding `unverified`.
- **Use tests as evidence.** Use tests to understand expected behavior and confirm
  suspected defects, but do not treat passing tests as proof of correctness.
  Missing tests are not automatically a finding; report the underlying behavioral
  defect and recommend a test that reproduces it. For parsers, serializers,
  state transitions, and other invariant-heavy logic, propose property-based tests
  when generated inputs would probe the contract better than more examples. For
  high-blast-radius logic, propose mutation testing when the question is whether
  passing tests actually detect meaningful behavioral changes. When an independent
  reference implementation, previous version, external service, or alternate
  calculation is a trustworthy oracle, propose differential tests over shared
  inputs after normalizing intentional differences. Another LLM's agreement is not
  an independent oracle, and a disagreement is evidence to investigate rather than
  automatic proof that the PR is wrong. Verification runs these checks only when
  the repository already provides the tooling; missing tooling is an advisory or
  follow-up proposal, not a finding in the PR.
- **Support every finding.** State the expected vs. actual behavior, the input and
  state required to trigger it, the execution path, the observable impact, and the
  verification evidence. Hand the Verification stage a repro recipe to run (§4.5);
  until it runs, mark the finding `unverified` and explain how to verify.

### 4.3 Security finder

Determine whether the change lets an unauthorized principal access protected
information, modify protected state, perform a restricted action, or cross an
intended isolation boundary.

- **Authentication and authorization.** Identify who can reach each affected entry
  point and which resources/actions it exposes. For every caller-controlled
  resource reference, verify the code establishes the caller's permission for that
  action on that specific resource — authentication, possession of an identifier,
  or access to a related resource does not by itself grant permission. Authorize
  each protected resource independently. Verify that missing identity/ownership
  fails closed and that early returns, alternate states, and fallbacks cannot
  bypass the decision. Check that list/search/lookup operations return only
  resources in the caller's scope.
- **Trace security context across components.** Follow identity, tenant, session,
  and permission context through service layers, background jobs, internal APIs,
  and external systems. When a downstream operation uses broader credentials than
  the caller, verify authorization happens before it. Flag boundaries where the
  caller's context is discarded, replaced with broader access, or reconstructed
  from untrusted input.
- **Untrusted input.** Trace untrusted input reaching queries, file paths, URLs,
  commands, templates, parsers, or logs. Verify inputs are validated for their
  expected format and used through safe APIs, especially where values are
  concatenated, decoded, interpolated, or forwarded across a trust boundary. Raise
  a finding only when a realistic input can reach a sensitive operation and produce
  an unsafe result.
- **Secrets and sensitive information.** Verify the change does not expose secrets
  or protected information through source, responses, logs, traces, errors,
  generated links, or external services. Treat tokens, signed URLs, and temporary
  credentials by everything they allow the holder to do; ensure they are created
  and returned only to authorized callers with appropriate scope.
- **Support every finding.** Name the unauthorized principal, the protected
  resource/action, the missing or bypassed control, the path to the sensitive
  operation, the impact, and the trigger conditions. Do not start servers or Docker
  yourself; hand the Verification stage a repro recipe to run (§4.5). Until it runs,
  mark the finding `unverified`. Report only problems introduced, exposed, or
  materially worsened by the PR — do not turn the review into a general security
  audit of nearby code.

### 4.4 Quality finder (style, efficiency, reuse)

- **Reuse.** Flag new code that duplicates an existing helper. Grep shared/utility
  modules and files adjacent to the change, and name the existing function to call
  instead. Classify `style` (usually `minor`/`nitpick`); if the duplicate diverges
  in behavior, `correctness`.
- **Style and patterns.** Flag style only against **codified conventions** —
  repository guidelines (`CLAUDE.md`), official style guides, and linter/formatter
  rules. Every `style` finding must **cite the specific codified rule** it violates,
  not reviewer taste. Uncodified personal preference is at most a `nitpick`.
- **Deterministic quality gates.** Inspect the repository's configured gates, such
  as cyclomatic-complexity thresholds, dependency rules, and schema checks. Confirm
  the change does not bypass or narrowly suppress them. Treat a configured gate as
  the codified rule; do not invent a complexity threshold during review or report
  the absence of a preferred tool as a PR defect.
- **Efficiency.** Check for clear efficiency regressions — obviously unnecessary or
  unbounded work on realistic paths: database/network calls inside growing loops;
  repeated computation or fetching; loading an entire dataset when a bounded subset
  suffices; unbounded memory accumulation; blocking work on a latency-sensitive
  path; or an algorithm whose cost grows impractically at the project's expected
  scale. Raise only when the expensive path is realistically reachable and the
  impact is explainable from the code or existing measurements. Do not report
  theoretical optimizations or minor constant-factor tweaks. For
  performance-sensitive changes, hand the benchmark to the Verification stage to
  run when an established setup exists (§4.5); until it runs, mark
  measurement-dependent claims `unverified`.

**Advisory notes (optional).** Two concerns are **not** classified on the §2 axes
or routed through §2.7 — report them as a short advisory note at the end of the
review, for the reviewer and implementer to act on at their discretion:

- **Infrastructure.** Whether the feature requires an infrastructure change.
- **Scalability.** Whether the feature introduces scalability issues at the
  project's expected scale.

### 4.5 Verification

Challenge each candidate finding and verify its execution path, scope, origin, and
evidence, then set its verification status per §2.6. **Verification is the single
owner of evidence *execution*.** It — and only it — runs the repro, executes any
change-verification skill when present, runs benchmarks against an established
setup, and captures the grounding logs/traces (e.g. Logfire). The finders never do: they run
in parallel, and each starting a uvicorn or Docker server would collide on ports —
so finders only *propose* how to reproduce, and Verification runs it serially.
Scale the evidence to Scope's blast-radius assessment. Run deterministic gates as
early as the repository workflow permits; for high-impact invariant-heavy changes,
run established property-based or mutation checks when they can confirm the
specific candidate rather than merely produce a score. Run established
differential checks when Scope identifies a trustworthy independent oracle; record
the compared implementations, inputs, intended normalizations, and mismatches.
Produce evidence for `blocking` and `major` findings here; a `blocking` finding
holds the hard merge gate only once `verified` (§2.6). Apply the **refuted bar**: a
candidate may be discarded only when provably false from the code (factually wrong
/ impossible / already guarded), with the contradicting line, invariant, or guard
cited. Honor a finder's `self-refuted` tag when its evidence meets the bar;
override it when it does not. Anything that cannot clear the bar stays a raised
`unverified` finding — never a silent drop.

### 4.6 Judge

- **Root-cause and deduplication.** Trace each surviving finding to its root cause
  (§2.5) and deduplicate, folding symptoms of one defect together and keeping
  genuinely distinct defects separate.
- **Label and route.** Assign the §2 labels and route each finding via §2.7.
- **Order.** Rank raised findings most-severe first (`blocking` → `major` →
  `minor`). **Render every raised finding — never trim for length.** By this stage
  each finding has cleared the refuted bar (§2.6) and must be fixed or dismissed
  (§3.3), so hiding any would only defer the work to a re-review that re-raises it;
  upstream noise control (negligible → none, batched nitpicks, cited-rule `style`,
  the finder guards, Verification) already keeps the list honest. A high finding
  count is signal, not noise: emit an advisory (§4.4) recommending the PR be split,
  rather than shortening the list.
- **Format.** Emit each finding in the §2.8 template.

## 5. Follow-ups & notes

- **`CLAUDE.md` footgun list.** Maintain the concrete, greppable
  language- and framework-pitfall checklist in `CLAUDE.md`, where §4.4's "cite the
  codified rule" points — not inline here, so the standard stays portable and
  project-agnostic.
- **Dedicated issue-filing skill (to build).** Create a separate skill that files
  the `GitHub issue` proposals from §2.7 deliberately, so issue creation is never an
  ad-hoc side effect of a review run.
