# Test plan: hardening this session's changes

Written 2026-07-31. Covers everything changed in this session - tickets 5, 6, 7, 8,
the removal of the `users.role` layer, the dead `admin-list` endpoint, and the
defensive-`getattr` cleanup - and asks of each change: *what would a leak look like,
and does anything fail when it happens?*

Scope note: this is not "add tests until the number goes up". The platform layer is
already at 100% line coverage and every suite is green, which is exactly the state in
which a tenant-isolation hole survives. Coverage says a line ran; it says nothing
about whether the refusal it was supposed to make was made. So the plan is organised
by **invariant**, not by module.

## P0 - a real leak found while writing this plan

### L1. `chosen` alert recipients are resolved across tenants

`NotificationService._named()` resolves author-supplied user ids with
`user_repo.get_by_id`, which is **global**. `member_repo.get_emails_for_users` exists
specifically to avoid this and says so: *"Restricted to members so a grant list cannot
be used to resolve the email of someone outside the tenant."*

Consequence: an agent in organization A can list a user id belonging to organization B
under `AlertSpec.to = [chosen]`, and that person receives mail whose body carries A's
organization name, the agent's name, the reason a run stopped and what it spent.

Requires the target's UUID and `agents:edit` in the attacking org, so it is not
trivially exploitable - but it breaks the platform's central invariant, and the whole
point of that invariant is that it does not depend on how hard the id is to guess.

**Rule to implement.** Audiences split in two, and the split is the fix:

| Audience | Derived from | Scoping |
|---|---|---|
| `admins` | roles + the `is_app_admin` flag | org members **plus** app admins, deliberately deployment-wide |
| `owner`, `initiator`, `chosen` | a user id | **must** be membership-scoped to the run's organization |

App admins staying deployment-wide is correct and already documented - they administer
the deployment. Everything keyed on a *person* must be scoped.

**Tests.** Unit: a foreign id under `chosen` contributes no address; a member id does.
Integration (real database, two tenants): the query genuinely cannot see the other
organization's member.

## What is already covered, and therefore not repeated

Established earlier in the session and passing:

| Area | Tests |
|---|---|
| Alert audience resolution, opt-outs, org-vs-agent budget scope | `tests/test_notifications.py` (28) |
| Spec validators - the four refused alert configurations | `tests/test_agent_spec_and_factory.py::TestWhoHearsAboutAnAgent` (7) |
| Per-agent report flow - bad spec, missing version, mail failure | `tests/test_report_tasks.py` (6) |
| Conversation routes always scoped to the caller | `tests/api/test_conversation_scoping.py` (4) |
| Collection counts - grouping, absent rows, failed documents | `test_kb_scoping.py` + `test_platform_flows.py::TestWhatACollectionReportsItHolds` |
| Builder UI - collections, model combobox, capability switches, alerts panel, model picker | 43 frontend tests |

The gaps below are what those do **not** reach.

## P1 - security invariants with no test at all

### S1. Privilege escalation through the user-update surface

`users.role` is gone, so the guard that used to strip it from `PATCH /users/me` is
gone too. What replaced it is an *absence*: `UserUpdate` carries no privilege field.
An absence is exactly the kind of thing a later edit re-adds by accident.

- `PATCH /users/me` with `is_app_admin: true` in the body does not grant it.
- `PATCH /users/me` with `role: "admin"` is not accepted as a field.
- `PATCH /users/{id}` (app admin) cannot grant `is_app_admin` either - the one global
  privilege is CLI-only by design.
- `UserUpdate.model_fields` contains no privilege field. A schema-level assertion,
  because it fails the moment somebody adds one rather than when a route is exercised.

Layer: `tests/api/`, plus one schema unit test.

### S2. `member_repo.list_app_admin_emails` is mocked everywhere

It decides who receives every alert. Every existing test patches it, so nothing
verifies the query. Needs a real database:

- returns an app admin who holds **no membership** in the organization - the whole
  reason it is not joined to `organization_members`
- excludes an inactive app admin
- excludes an app admin who switched that specific preference off
- excludes an ordinary member
- honours the preference column named, not a different one

Layer: `tests/integration/`.

### S3. `agent_repo.list_all_published` is a deliberate cross-tenant read

Mocked in the report tests. It is one of the few functions that reads across every
organization, so what it selects is a security property:

- returns published agents from **both** tenants
- excludes drafts and archived agents

Layer: `tests/integration/`.

### S4. No plaintext leaks on the surfaces added this session

`tests/api/test_no_secret_escapes.py` is the existing net. Extend for:

- the knowledge-base listing with its new count fields
- `GET /me/permissions` after the role removal
- an alert-carrying agent spec round-tripped through the API - `user_ids` are ids, and
  no email may appear in the response

## P2 - correctness gaps in this session's code

### C1. Collection counts must respect access before counting

`counts_for` is handed the rows `list_accessible` already filtered, so it cannot leak
by construction - but that is an argument, not a test. One integration test: a
collection in another organization contributes nothing to the caller's counts.

### C2. `BudgetScope` decides an audience, so its plumbing is security-relevant

Covered at the notifier. Not covered: that a run stopped by the *organization's* cap
actually arrives with `BudgetScope.ORGANIZATION` from the code that raises it.
`assert_organization_within_budget` and the factory's two limits.

### C3. The migration is reversible with data present

`0066` drops a column. `make test-migrations` currently fails on this developer's
populated database for an unrelated reason (an FK re-add in an earlier migration), so
the down path was verified by hand. Pin it: upgrade, downgrade, upgrade with user rows
present, asserting the column returns at its old default.

Layer: `tests/integration/`.

## P3 - frontend gaps

| # | What | Why it matters |
|---|---|---|
| F1 | `MarkdownEditor` | Source/Preview toggle, the label is the accessible name, empty state. Untested component shipped this session |
| F2 | `RunSummary` | The failed-run count and the `+` on a partial cost are the two things an operator reads; a wrong tally is a silent lie |
| F3 | Agents page status filter | The Select replaced a segmented control; archived agents are only fetched for two of the four filters |
| F4 | Activity `?agent=` | The Builder's hand-off. A filter that silently does nothing sends somebody to the wrong history |
| F5 | `isAppAdmin` | The `role === "admin"` fallback is gone. One test that the flag alone decides, and that `undefined` is not admin |

## Order of work

1. **L1** - fix the leak, regression test both layers. Nothing else matters until this is done.
2. **S1, S2, S3, S4** - the security invariants.
3. **C1, C2, C3**.
4. **F1-F5**.
5. `make check` and `make test-integration` green; confirm each new test fails against
   the pre-fix behaviour where that is meaningful.

## Standing rule for every test below

Assert the consequence, cover the refusal, and prove the test can fail. A test written
against code that already works, which nobody has seen fail, is a test that was never
tested.
