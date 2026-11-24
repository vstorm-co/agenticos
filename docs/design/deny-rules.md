# Org-level deny rules: scoped proposal (Fix 3C)

Status: **proposal only, 2026-11-24**. This document creates no table, no
endpoint and no enforcement. It is the scoped proposal the adoption audit and
the usability plan left as Fix 3C, to be decided on its own before any code is
written.

Sources: the T3OS adoption audit (section 7, "no deny rule") and the T3OS
usability plan (Phase 3C, 10–15 dev-days, high risk). Both live outside this
repository, in the T3OS alignment workspace; this document is the proposal
they call for, written against this repository's code.
Phase 3C is sequenced after Fix 3A (plain-language activity feed) and Fix 3B
(grant lifecycle) are live and reviewed; it is the riskiest change in that
plan and is not bundled with either.

## 1. The problem

Today there is no way for an organization to say "nobody may do X". Refusal
is by *absence* of a grant, which is not the same as an explicit, auditable
"denied".

### What the model has today

Three independent layers, documented in [Permissions](../permissions.md):

1. **Role scopes.** `ROLE_PERMS` in `backend/app/core/permissions.py` maps
   each role to permissions at a `Scope` — `NONE < OWN < SHARED < TEAM <
   ALL`. A role says how much of a resource *type* a member reaches.
2. **Visibility and grants.** A resource is `private`, `team` or `org`
   (`Visibility` in `backend/app/db/models/resource_grant.py`), and a
   `ResourceGrant` gives one member or one group a level — `read`, `use`,
   `edit`, `edit_data` (the last pages-only) — on one row.
3. **Combination by maximum.** `resolve_access` in
   `backend/app/services/access.py` answers `max(role scope, grant on this
   row)`. The module docstring states it plainly: "A grant can widen what a
   role allows for a single row; it never narrows it." `docs/permissions.md`
   repeats the rule as a warning: "A grant widens what a role allows; it
   never narrows it."

There is no fourth layer that narrows. A grep for `deny` across
`backend/app/core/permissions.py` and `backend/app/services/access.py`
returns nothing.

### The two deny-like mechanisms that already exist are not this

- **Sandbox file rules** (`backend/app/agents/capabilities/sandbox/_permissions.py`).
  Per-agent, per-run. `workspace_ruleset()` allows the workspace and denies
  off-limits paths (secrets and system patterns from the library). Its own
  docstring states the division of labour: "the ruleset denies, the platform
  asks." It says nothing about the organization, and it cannot express "no
  agent in this org may send email externally".
- **Web-fetch domain filters** (`backend/app/agents/capabilities/web_fetch/__init__.py`).
  Per-agent spec config: `allowed_domains` and `blocked_domains`, bare
  hostnames matched exactly. A per-agent setting on one capability, not an
  org policy — every agent would need the same list, and nothing stops an
  author leaving it off.

### What breaks without it

- An Owner cannot forbid a class of action org-wide ("never send anything
  externally", "never share a finance agent outside Finance"). The only
  tools are removing grants one row at a time, or narrowing a role — which
  also removes legitimate access and is invisible as a policy decision.
- A refusal leaves no policy trace. `resolve_access` returning `False`
  because no grant exists is indistinguishable, in the audit log, from a
  deliberate organizational refusal. Sharing changes *are* audited
  (`resource.share`, `resource.visibility_changed` in
  `backend/app/services/sharing.py`), but there is no `denied by rule`
  event to audit, because there is no rule.
- Approval cannot substitute. The approval gate
  (`backend/app/agents/capabilities/approval/_capability.py`, `ApprovalGate`)
  parks a tool call for a human to answer. Asking a human to approve
  something the organization forbids is the wrong queue: it trains people
  to click through, and the one time somebody approves, the forbidden thing
  happens with a human's name on it.

## 2. The proposed model

### One rule: deny is evaluated before grants, and wins

```
effective access = deny? → refused : max(role scope, grant on this row)
```

A deny rule is an org-level row that names a *target* and refuses it. It is
checked at the top of `resolve_access`, after the tenancy check and before
the role-scope check — so it also covers the managed-table override
(`table_access` in the same function), which today answers before scopes and
grants are consulted. Order inside `resolve_access` becomes: subject →
same organization → **deny rules** → managed-table override → role scope →
grant.

Deny never widens anything. It can only refuse what a role or a grant would
otherwise allow, which is what makes it safe to reason about: adding a rule
removes access, it never creates it.

### What a rule can target

| Target | Example | Notes |
| --- | --- | --- |
| Action (`Perm`) | `agents:run`, `workflows:run`, `artifacts:edit` | The permission catalog in `backend/app/core/permissions.py` is the vocabulary; a rule names a value from it, never a free-text string. |
| Tool | `send_email`, `web_fetch`, an MCP tool id | The stable tool id from the capability registry, as `tool_approval` keys on it in `backend/app/agents/spec.py`. |
| Destination | an external email domain, a webhook URL host, a blocked hostname | Same canonicalisation problem as the web-fetch filters: compare A-labels, not raw strings (`a_label` in `backend/app/agents/capabilities/web_fetch/_capability.py`). |
| Agent | one agent, or every agent in the org | "No agent may do X" is the org-wide case; "this agent may never do X" is the per-agent case, and must not become a second spec field. |
| Group | members of Finance, members of Contractors | Groups already exist as grant subjects (`subject_group_id`); a rule targets the same groups. |
| Data class | "finance data", "personal data" | **Not in v1.** No classification exists to target today; see open decision 6. |

A rule may combine targets (action + group, tool + destination). An empty
slot in a rule means "any" for that slot. A rule with every slot empty is
refused at creation: "deny everything" is not a rule, it is an outage.

### Precedence and conflicts

- **Deny beats grant, always.** There is no conflict to resolve between a
  deny rule and a grant: the rule wins, and the audit entry says so.
- **Deny beats role scope, always**, subject to open decision 3 (whether it
  beats an Owner, and whether it beats the app-admin bypass).
- **Two deny rules never conflict.** Both refuse; the one named in the audit
  entry and the user-facing message is the most specific match, then the
  lowest `priority` value. `priority` exists so the message is
  deterministic, not so one rule can override another — no rule ever
  permits.
- **A deny rule and an approval requirement do not conflict either.** Deny
  is checked first: a denied call is refused outright and is never parked
  for approval. An approval queue must never be asked to approve something
  the org forbids.

### How a denial surfaces

- **Audit entry, always.** Via `record_audit` in `backend/app/core/audit.py`,
  in the caller's transaction, alongside the existing `resource.share` and
  `resource.visibility_changed` entries. Proposed action:
  `access.denied_by_rule`, with `details` carrying the rule id, the matched
  target, the actor and the permission or tool refused. The audit log's hash
  chain and append-only checkpoint ([Governance](../governance.md)) are what
  make "we refused this, and here is the rule" a statement an auditor can
  rely on rather than a log line.
- **User-facing message naming the rule.** For example: "Blocked by org
  rule 'No external email' — ask an admin for an exception." The person
  refused needs to know *which* rule and *whom* to ask; a bare "forbidden"
  sends them to support with nothing to quote. Whether the rule's name is
  shown to every denied user or only to members is open decision 5.
- **No silent refusal in listings.** Where a deny removes `view` access to a
  row, the row disappears from listings the same way a missing grant hides
  it today. Where it removes only `run` or `edit`, the row stays visible and
  the action refuses with the rule named. The two must not be confused: a
  hidden row is a mystery, a refused button with a reason is a policy.

## 3. Scope and non-goals

This proposal is **not**:

- **A replacement for grants or visibility.** Grants widen, visibility
  narrows per row, roles scope per type. Deny rules are the fourth layer,
  org-wide and explicit. None of the three changes.
- **Sandbox file rules.** `workspace_ruleset()` stays per-agent and
  per-run; deny rules do not touch it. An org rule can forbid the file
  tools entirely, but it cannot express path patterns — that stays where it
  is.
- **A replacement for approval.** Approval asks a human; deny refuses
  without asking. A tool can be both gated (needs approval) and deniable
  (never, for this target) — deny is checked first.
- **A web-fetch allowlist.** `allowed_domains` / `blocked_domains` stay
  per-agent spec config. A deny rule on a destination is org-wide and
  applies across capabilities, not one capability's config.
- **Content filtering or guardrails.** A deny rule refuses an *action* to a
  *target*. It does not read message content, classify data, or judge a
  model's words. Data-class targeting waits on a classification that does
  not exist yet.
- **A DLP or exfiltration product.** It stops the actions it names at the
  enforcement points in section 4. It does not inspect payloads, and a
  determined agent with an allowed tool can still copy text by hand. Anyone
  promising otherwise is selling a different feature.

## 4. Evaluation points

Every point that can let the forbidden thing happen must check the rules.
The list below is the complete set for v1; anything not listed is out of
scope until a later phase names it.

| # | Enforcement point | What changes |
| --- | --- | --- |
| 1 | `resolve_access` (`backend/app/services/access.py`) | Deny check at the top, after tenancy, before scope and grants. This is the single chokepoint every route depends on — which is why this phase is high risk, and why it is its own proposal. |
| 2 | Listings: `accessible_ids` / `visible_resource_ids` (same module) | A deny on `view` must hide the row; a deny on `run`/`edit` must not. Listings batch grants in one query today; deny evaluation must batch the same way, not add a query per row. |
| 3 | Approval path: `ApprovalGate` (`backend/app/agents/capabilities/approval/_capability.py`) and `ApprovalService.decide` (`backend/app/services/approvals.py`) | A denied call is refused before it is parked, and `decide` re-checks at decision time — a rule created while an approval waits must still refuse it. |
| 4 | Tool execution: the factory's `approval_required_tools` resolution (`backend/app/agents/factory.py`) | A tool denied for this run's targets is dropped from the toolset where it is statically known (the sandbox pattern: the model never sees it), and refused at call time with the rule named where it is dynamic (MCP tools, whose approval is a binding property, not a name). |
| 5 | Sharing: `SharingService.share`, `share_with_group`, `set_visibility` (`backend/app/services/sharing.py`) | A deny on sharing with a group, or on making a resource org-visible, refuses — or defers through the existing `SharingGuard` / `Deferred` mechanism where a request is the right answer. Note sharing is intra-org only today (a grant naming an outsider is refused), so "never share outside the org" is already the default; the new value is "never share *this* with *them*". |
| 6 | Run admission for triggers, schedules and channels | A run acting as its creator (`fired_as_creator`, `AuthContext` in `backend/app/core/permissions.py`) or as a publisher (`publisher_context`) is still subject to the org's deny rules. A rule that only binds interactive chats is a rule with a hole in it. |

Explicitly **not** enforcement points in v1: model output and guardrails,
the sandbox path rules, per-agent web-fetch filters, and the console's
client-side permission gates (which hide buttons but never decide access —
the server decides).

## 5. Data model and migration sketch

No existing table changes in v1. One new table, one new permission, new
audit action strings (which need no schema change).

```sql
-- New table: deny_rules (Alembic revision following
-- backend/alembic/versions/0299_merge_personal_composio.py; the number is
-- assigned at implementation time — migration numbering restarted after the
-- baseline squash, so verify against backend/alembic/versions/).
CREATE TABLE deny_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,                       -- shown in the refusal message
    description TEXT,
    action TEXT,                              -- a Perm value, e.g. 'agents:run'; NULL = any
    tool_id TEXT,                             -- stable capability tool id; NULL = any
    destination TEXT,                         -- canonicalised host/domain; NULL = any
    agent_id UUID REFERENCES agents(id) ON DELETE CASCADE,  -- NULL = every agent
    group_id UUID REFERENCES groups(id) ON DELETE CASCADE,  -- NULL = every member
    priority INTEGER NOT NULL DEFAULT 100,    -- lowest wins, for the message only
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_deny_rules_org_enabled ON deny_rules (organization_id, enabled);
```

- **Permission.** A new global permission in the `Perm` catalog
  (`backend/app/core/permissions.py`), e.g.
  `DENY_RULES_MANAGE = "deny_rules:manage"`, held by Owner (and Admin, if
  open decision 2 says so). Nothing in the catalog models one permission
  implying another, so authoring rules must not silently carry
  `roles:manage` or `org:settings` with it.
- **Audit.** Rule lifecycle (`deny_rule.created`, `.updated`, `.deleted`,
  `.enabled`, `.disabled`) and every refusal (`access.denied_by_rule`) go
  through `record_audit`, in the caller's transaction, like the sharing
  entries today.
- **No row is ever silently widened.** Disabling or deleting a rule restores
  exactly the access the role and grants already gave — it cannot grant
  anything itself. That is the property that makes a mistaken rule
  recoverable, and it is what the tests must pin.
- **Backfill: none.** A deployment with no rules behaves exactly as today.
  Rules are created after the migration, by a person, through the API.

## 6. Phased rollout

Rough effort per phase; total 10–15 dev-days, matching the usability plan's
Phase 3C estimate. Each phase lands separately and is reversible.

| Phase | What ships | Rough effort |
| --- | --- | --- |
| 0 | This proposal, plus the open decisions in section 8 answered. | Done (~0.5 day) |
| 1 | Model + migration + rule CRUD API + lifecycle audit. Evaluation in **shadow mode**: rules are matched and every would-deny is written to the audit log, but nothing is refused. The shadow log is the pre-flight report for phase 2. | 3–4 dev-days |
| 2 | Enforcement behind an org flag, at points 1–4 of section 4 (access resolution, listings, approval path, tool execution). Read-only rules view in the console. Flag on for one pilot org first. | 4–6 dev-days |
| 3 | Sharing and run-admission points (5–6), console authoring UI, default-on for new orgs, flag flip for existing orgs after their shadow report is reviewed. | 3–5 dev-days |

Sequencing constraints: phase 1 needs the decisions in section 8; phase 2
needs Fix 3A/3B live and reviewed (the plan's ordering — 3C touches
`resolve_access`, and 3A/3B must not be moving under it); phase 3 needs a
pilot org's shadow report showing no legitimate automation would break.

## 7. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| **Performance on every gated call.** `resolve_access` is the chokepoint every route depends on; a deny lookup per call taxes all of them. | Load the org's enabled rules once per request (the `AuthContext` is built once per request today) and match in memory; batch listings the way grants are batched (`visible_resource_ids` does one query, not one per row). Measure before phase 2 ships; a rule set is small (tens, not thousands) and that is a property to keep, not assume — cap rules per org. |
| **Rule-vs-grant confusion.** Two mechanisms now answer "may I?", and the next person to debug access will check the wrong one. | One documented formula (section 2), one audit action naming the rule, and the refusal message naming it. `docs/permissions.md` gains a fourth layer in the same change that ships enforcement — this proposal does not edit it, because no behaviour changes yet. |
| **Breaking existing automations.** A new rule can silently park a schedule, a routine or a channel flow that has run for months. | Shadow mode (phase 1) produces the "what would break" report before anything is enforced; phase 2 is flag-gated per org; the report names the affected agents and runs, not just a count. |
| **A wrong rule locks the org out of its own tools.** "Deny `agents:run` for everyone" is one careless row. | A rule with every target empty is refused at creation; a break-glass path lets an Owner disable rules (itself audited); deletion restores prior access exactly, per section 5. Whether deny can bind an Owner at all is open decision 3. |
| **Listings and enforcement disagree.** A row hidden in a list but runnable by id (or the reverse) is a hole, or a mystery. | Points 1 and 2 ship together in phase 2, with tests pinning both directions for each permission. |
| **MCP and dynamic tools cannot be dropped statically.** Their approval is a binding property (`ApprovalMarked`), not a name. | Refuse at call time with the rule named (point 4). Accept the weaker UX for dynamic tools rather than pretending the static drop covers them. |
| **Deny becomes a second approval queue.** If every refusal needs a human exception, the feature is a bottleneck wearing a policy's clothes. | No exception workflow in v1. Exceptions are a named later phase with their own decisions (time-boxed waiver, who approves); shipping them with v1 doubles the design. |

## 8. Open decisions for Sherman

1. **Default posture.** Default-allow with explicit denies (this proposal),
   or default-deny for a named set — e.g. external sends are denied unless
   a rule explicitly permits them? The second is a bigger change (it inverts
   the formula) and should not be smuggled into v1.
2. **Who authors rules.** Owner only, or Admin too? This decides who holds
   the new `deny_rules:manage` permission.
3. **Does deny override an Owner?** And does it override the app-admin
   bypass (`AuthContext.permissions` returns every permission at `ALL` for
   an app admin)? "Deny binds everyone including Owners" is the strongest
   reading and the easiest to get wrong; "Owners are exempt" leaves the
   most powerful account outside the policy.
4. **Break-glass.** When a rule locks the org out, who can disable it, and
   is that disable itself audited and alerted? (Proposal: Owner only,
   audited, alert to all admins.)
5. **What the denied user sees.** The refusal names the rule (proposal);
   is the rule's name and description shown to any denied member, or only
   to admins? A member who cannot see why was refused cannot fix it; a
   member who can see every rule can probe the policy.
6. **Data-class targeting.** Is there a classification to target in v1
   (finance, personal data), or is v1 limited to action, tool,
   destination, agent and group? If classification is wanted, it is its own
   design first.
7. **First rules to ship with.** Which concrete rules should exist on day
   one — e.g. "never send email externally", "never share a finance agent
   outside Finance", "no agent may call X"? The first rules are the
   acceptance test for the model: if they cannot be expressed, the model is
   wrong.

## References

- [Permissions](../permissions.md) — the three layers, and the
  `max(role scope, grant)` formula this proposal adds a deny step in front
  of. In particular [How the layers combine](../permissions.md#how-the-layers-combine).
- [Governance](../governance.md) — budgets, approvals and the audit trail;
  the approval queue in [Approvals](../governance.md#approvals) is what a
  denial must never be parked in.
- `backend/app/core/permissions.py` — `Perm`, `Scope`, `ROLE_PERMS`,
  `AuthContext`.
- `backend/app/services/access.py` — `resolve_access`,
  `accessible_ids`, `visible_resource_ids`.
- `backend/app/db/models/resource_grant.py` — `Visibility`, `GrantLevel`,
  `ResourceGrant`.
- `backend/app/services/sharing.py` — `SharingService`, `SharingGuard`,
  `Deferred`.
- `backend/app/agents/capabilities/sandbox/_permissions.py` —
  `workspace_ruleset()`.
- `backend/app/agents/capabilities/web_fetch/__init__.py` —
  `allowed_domains` / `blocked_domains`.
- `backend/app/agents/spec.py` — `approval`, `tool_approval`.
- `backend/app/agents/capabilities/approval/_capability.py` —
  `ApprovalGate`.
- `backend/app/services/approvals.py` — `ApprovalService.decide`.
- `backend/app/core/audit.py` — `record_audit`.
