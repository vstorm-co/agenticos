# Source and modifications

This skill is adapted from Anthropic's anthropics/financial-services repository, pinned to commit `60565064557ca77b12f62aa7877f365d111c129d`. Original material is licensed under Apache License 2.0; the complete license is included in [LICENSE.txt](LICENSE.txt). This is a t3OS adaptation, not an Anthropic service or a promise that its connectors, subagents, or runtime are installed.

## Upstream skill copies

- [plugins/agent-plugins/kyc-screener/skills/kyc-rules/SKILL.md](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/kyc-screener/skills/kyc-rules/SKILL.md) — blob `1c0f271a2f8ebd308096101786ae60c027a0f886`.

## Modifications made on 2026-11-10

- Renamed the skill to `anthropic-fs-kyc-rules`, added the t3OS finance category, and rewrote runtime assumptions to use only exposed, authorized tools.
- Added engagement, jurisdiction, currency, evidence, missing-data, review, and artifact-validation requirements.
- Namespaced bundled skill references, retained required Markdown reference resources, and removed unavailable Office, managed-runtime, example-workbook, and recalculation-script assumptions.
- Outputs remain drafts. Posting, payment, trades, filings, onboarding approval, publication, and sending are outside this template's authority.

- Replaced clearance with a review-ready recommendation and human decision pending; added incomplete/undetermined outcomes, screening provenance, current approved rules, and explicit missing-screening handling; removed an implied escalator agent.

## Verification boundary

The repository checks catalog loading, provenance, and text-resource integrity. Runtime package availability, source-system access, generated artifacts, recalculation, rendering, accounting judgments, and deployment remain separate checks for the configured agent and engagement.
