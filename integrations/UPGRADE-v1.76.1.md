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
