# Source and modifications

This skill is adapted from Anthropic's anthropics/financial-services repository, pinned to commit `60565064557ca77b12f62aa7877f365d111c129d`. Original material is licensed under Apache License 2.0; the complete license is included in [LICENSE.txt](LICENSE.txt). This is a t3OS adaptation, not an Anthropic service or a promise that its connectors, subagents, or runtime are installed.

## Upstream skill copies

- [plugins/agent-plugins/model-builder/skills/3-statement-model/SKILL.md](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/model-builder/skills/3-statement-model/SKILL.md) — blob `01bcfe1d0db56ab910400531c280735cd118d734`.
- [plugins/agent-plugins/pitch-agent/skills/3-statement-model/SKILL.md](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/pitch-agent/skills/3-statement-model/SKILL.md) — blob `01bcfe1d0db56ab910400531c280735cd118d734`.

## Modifications made on 2026-11-10

- Renamed the skill to `anthropic-fs-3-statement-model`, added the t3OS finance category, and rewrote runtime assumptions to use only exposed, authorized tools.
- Added engagement, jurisdiction, currency, evidence, missing-data, review, and artifact-validation requirements.
- Namespaced bundled skill references, retained required Markdown reference resources, and removed unavailable Office, managed-runtime, example-workbook, and recalculation-script assumptions.
- Outputs remain drafts. Posting, payment, trades, filings, onboarding approval, publication, and sending are outside this template's authority.

## Included reference resources

- [references/formatting.md](references/formatting.md) from `plugins/agent-plugins/model-builder/skills/3-statement-model/references/formatting.md` (blob `1fbe938c1623ea73c9707b15775f0f92e21c948f`).
- [references/formulas.md](references/formulas.md) from `plugins/agent-plugins/model-builder/skills/3-statement-model/references/formulas.md` (blob `db2645727e258a4543c13925dab3c0ced7d40d90`).
- [references/sec-filings.md](references/sec-filings.md) from `plugins/agent-plugins/model-builder/skills/3-statement-model/references/sec-filings.md` (blob `e0fa48453a151a8d6770dda9c8b2ecede0fe363b`).

- Corrected the source's separate SBC add-back to retained earnings and taxable-income-to-net-income shortcut; replaced universal US tax-loss and zero-opening-balance assumptions with jurisdiction-specific approved inputs, recognized deferred-tax requirements, and reconciling schedules. Reworked the formula reference into a self-contained set of linkages with no unexplained balancing plugs.

## Verification boundary

The repository checks catalog loading, provenance, and text-resource integrity. Runtime package availability, source-system access, generated artifacts, recalculation, rendering, accounting judgments, and deployment remain separate checks for the configured agent and engagement.
