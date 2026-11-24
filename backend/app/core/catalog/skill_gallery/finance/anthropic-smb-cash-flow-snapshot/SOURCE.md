# Source and adaptation

Anthropic official source, adapted for t3OS; this adaptation is not an Anthropic-endorsed integration.

- Repository: [anthropics/knowledge-work-plugins](https://github.com/anthropics/knowledge-work-plugins)
- Pinned commit: `e605d8ddbfb688da57dfaaceebd93f12a64ef1d3`
- Source: [small-business/skills/cash-flow-snapshot/SKILL.md](https://github.com/anthropics/knowledge-work-plugins/blob/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3/small-business/skills/cash-flow-snapshot/SKILL.md)
- Source SHA-256: `1e5584378c5817981899bfa81296d8a9c2a7e4381a2f1deed616194e51944fff`
- License: Apache-2.0; the complete upstream license is in [LICENSE](LICENSE).
- Adapted for t3OS on 2026-11-10.

## Changes

- Rewrote the main workflow and substantive reference procedures as a faithful self-contained t3OS accounting-preparation adaptation, retaining the source work sequence, essential evidence checks and all bundled reference/shared resource paths.
- Removed external bill/vendor creation, approval, sync, posting, payments, message sending, payment-link creation, scheduling and page-publishing instructions throughout the active workflow and references.
- Replaced fixed connector recipes and product-wide capability claims with actual-schema checks, source-of-record reconciliation and scoped-export fallback; no connector installation or unbound skill is assumed.
- Adapted shared client isolation, completeness, currency, privacy, voice and artifact policies; client-specific context is not written into immutable shared catalog resources.
- Mapped skill continuations to actual installed names when available, documented read_skill/read_skill_resource, and normalized resource links to registered skill-root names.
- Replaced the upstream heuristic percentage-on-signed-net range and inconsistent worked dates with dated scenario cash flows, opening-plus-cumulative-net roll-forwards, an internally consistent example and explicit nonstatistical scenario labels.

The pinned source records provenance, not live regulatory guidance or a connected account. References to frameworks, tax rules, connector capabilities and example thresholds must be checked against the engagement and currently exposed tools. The content prepares evidence and draft outputs for human review; installing it does not connect applications, grant authority or publish an agent.

## Bundled resource mapping

| Local resource | Pinned upstream source |
|---|---|
| `shared/absent-is-not-zero.md` | [small-business/shared/absent-is-not-zero.md](https://github.com/anthropics/knowledge-work-plugins/blob/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3/small-business/shared/absent-is-not-zero.md) |
| `shared/artifact-style.md` | [small-business/shared/artifact-style.md](https://github.com/anthropics/knowledge-work-plugins/blob/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3/small-business/shared/artifact-style.md) |
| `shared/chain-seams.md` | [small-business/shared/chain-seams.md](https://github.com/anthropics/knowledge-work-plugins/blob/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3/small-business/shared/chain-seams.md) |
| `shared/connector-call-shapes.md` | [small-business/shared/connector-call-shapes.md](https://github.com/anthropics/knowledge-work-plugins/blob/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3/small-business/shared/connector-call-shapes.md) |
| `shared/connector-neutrality.md` | [small-business/shared/connector-neutrality.md](https://github.com/anthropics/knowledge-work-plugins/blob/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3/small-business/shared/connector-neutrality.md) |
| `shared/crm-of-record.md` | [small-business/shared/crm-of-record.md](https://github.com/anthropics/knowledge-work-plugins/blob/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3/small-business/shared/crm-of-record.md) |
| `shared/currency-and-locale.md` | [small-business/shared/currency-and-locale.md](https://github.com/anthropics/knowledge-work-plugins/blob/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3/small-business/shared/currency-and-locale.md) |
| `shared/document-format.md` | [small-business/shared/document-format.md](https://github.com/anthropics/knowledge-work-plugins/blob/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3/small-business/shared/document-format.md) |
| `shared/gmail-inbox-traps.md` | [small-business/shared/gmail-inbox-traps.md](https://github.com/anthropics/knowledge-work-plugins/blob/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3/small-business/shared/gmail-inbox-traps.md) |
| `shared/personal-data.md` | [small-business/shared/personal-data.md](https://github.com/anthropics/knowledge-work-plugins/blob/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3/small-business/shared/personal-data.md) |
| `shared/quickbooks-report-traps.md` | [small-business/shared/quickbooks-report-traps.md](https://github.com/anthropics/knowledge-work-plugins/blob/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3/small-business/shared/quickbooks-report-traps.md) |
| `shared/reference/artifact-example.html` | [small-business/shared/reference/artifact-example.html](https://github.com/anthropics/knowledge-work-plugins/blob/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3/small-business/shared/reference/artifact-example.html) |
| `shared/tenant-scope.md` | [small-business/shared/tenant-scope.md](https://github.com/anthropics/knowledge-work-plugins/blob/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3/small-business/shared/tenant-scope.md) |
| `shared/untrusted-content.md` | [small-business/shared/untrusted-content.md](https://github.com/anthropics/knowledge-work-plugins/blob/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3/small-business/shared/untrusted-content.md) |
| `shared/voice-profile.md` | [small-business/shared/voice-profile.md](https://github.com/anthropics/knowledge-work-plugins/blob/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3/small-business/shared/voice-profile.md) |
| `reference/examples/worked-example.md` | [small-business/skills/cash-flow-snapshot/reference/examples/worked-example.md](https://github.com/anthropics/knowledge-work-plugins/blob/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3/small-business/skills/cash-flow-snapshot/reference/examples/worked-example.md) |
| `reference/gotchas.md` | [small-business/skills/cash-flow-snapshot/reference/gotchas.md](https://github.com/anthropics/knowledge-work-plugins/blob/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3/small-business/skills/cash-flow-snapshot/reference/gotchas.md) |
| `reference/v2_sources.md` | [small-business/skills/cash-flow-snapshot/reference/v2_sources.md](https://github.com/anthropics/knowledge-work-plugins/blob/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3/small-business/skills/cash-flow-snapshot/reference/v2_sources.md) |
| `LICENSE` | [LICENSE](https://github.com/anthropics/knowledge-work-plugins/blob/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3/LICENSE) |
