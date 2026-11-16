# Upstream v1.76.1 candidate

Source: `vstorm-co/agenticos` tag `v1.76.1`, commit
`9a9399dd3e80e8eef60316d2a23a956b185a7f46`.
Initial T3 parent: `6bacea53b5cb43f9f75d07e554b37668ca9e80c6`.

This candidate preserves T3 ancestry and incorporates the v1.74–v1.76.1
changes. It is not a deployment or downstream acceptance record.

## Scope

- Opt-in automatic channel participation, organization-group approval audiences,
  and expanded channel history/report tools.
- App PDF export and updated authoring tools.
- HMAC API-webhook verification and native Linear webhook triggers.
- Upstream access, replay-redaction and telemetry dependency fixes.

Existing personal model connection rules, T3 permissions and active feature
branches must remain compatible. Channel participation remains opt-in; this
update does not configure accounts or enable participation on a deployment.

## Release gates

Run the full current-source CI, coverage, build, security, documentation and
browser gates before considering a merge. Validate migrations on an isolated
pgvector database, including upgrade, empty downgrade/re-upgrade and model
parity. Preserve historical migration IDs. Coordinate any unmerged feature
migration train against the resulting graph before combining it.

Capture the live source/image digests, current database revision, worker pools,
storage topology and recoverable backup before a separate deployment decision.
No production database, credentials, permissions or running resources were
changed while preparing this candidate.

Betty and SL Grease downstream propagation requires the existing exact-commit
successful validation workflow plus each consumer's compatibility checks.
Their pins are intentionally unchanged by this PR.

## Candidate verification (2026-11-16)

The candidate was reconciled with T3 `83ba9d84768d9b3950bd5c56f7e1a1b7b7c93cf7`.
Focused backend tests: 581 passed. Focused frontend tests: 402 passed on the
initial candidate, then 137 selector/chat/catalog cases passed after reconciliation.
Full frontend TypeScript passed with a 4 GiB Node heap; the earlier default-heap
attempt exhausted memory. Scoped lint/format and documentation paragraph/build
checks passed.

A disposable PostgreSQL 17.11 cluster with pgvector 0.8.0 completed upgrade to
`0331_merge_t3_rooms_and_v1761`, downgrade to base, re-upgrade and model-parity
checks. Alembic reported no new upgrade operations. This is isolated PostgreSQL
17 evidence, not the repository CI PostgreSQL 16 image or a production-sized
rehearsal. The existing table-sort-cycle warning was retained. No historical
migration was modified and no production data was used.

Complete current-head CI, coverage, security and browser gates remain mandatory;
the local results above do not replace them.
