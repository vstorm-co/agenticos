# Source and modifications

This skill is adapted from Anthropic's anthropics/financial-services repository, pinned to commit `60565064557ca77b12f62aa7877f365d111c129d`. Original material is licensed under Apache License 2.0; the complete license is included in [LICENSE.txt](LICENSE.txt). This is a t3OS adaptation, not an Anthropic service or a promise that its connectors, subagents, or runtime are installed.

## Upstream skill copies

- [plugins/agent-plugins/market-researcher/skills/competitive-analysis/SKILL.md](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/market-researcher/skills/competitive-analysis/SKILL.md) — blob `2632b3d1507424ac2d81578c7e05f81e7d54791d`.

## Modifications made on 2026-11-10

- Renamed the skill to `anthropic-fs-competitive-analysis`, added the t3OS finance category, and rewrote runtime assumptions to use only exposed, authorized tools.
- Added engagement, jurisdiction, currency, evidence, missing-data, review, and artifact-validation requirements.
- Namespaced bundled skill references, retained required Markdown reference resources, and removed unavailable Office, managed-runtime, example-workbook, and recalculation-script assumptions.
- Outputs remain drafts. Posting, payment, trades, filings, onboarding approval, publication, and sending are outside this template's authority.

## Included reference resources

- [references/frameworks.md](references/frameworks.md) from `plugins/agent-plugins/market-researcher/skills/competitive-analysis/references/frameworks.md` (blob `66b9f3d138db176c0a0a1a8caa0e7c97bc92eb61`).
- [references/schemas.md](references/schemas.md) from `plugins/agent-plugins/market-researcher/skills/competitive-analysis/references/schemas.md` (blob `8449f144ee4a0f33baf4f78824a79e0ffce3be76`).

- Removed the source platform's assumed four-question tool limit in favor of the actual exposed user-question tool.

## Verification boundary

The repository checks catalog loading, provenance, and text-resource integrity. Runtime package availability, source-system access, generated artifacts, recalculation, rendering, accounting judgments, and deployment remain separate checks for the configured agent and engagement.
