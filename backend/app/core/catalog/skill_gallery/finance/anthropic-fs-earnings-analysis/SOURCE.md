# Source and modifications

This skill is adapted from Anthropic's anthropics/financial-services repository, pinned to commit `60565064557ca77b12f62aa7877f365d111c129d`. Original material is licensed under Apache License 2.0; the complete license is included in [LICENSE.txt](LICENSE.txt). This is a t3OS adaptation, not an Anthropic service or a promise that its connectors, subagents, or runtime are installed.

## Upstream skill copies

- [plugins/agent-plugins/earnings-reviewer/skills/earnings-analysis/SKILL.md](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/earnings-reviewer/skills/earnings-analysis/SKILL.md) — blob `447de2f9ec277f976eb2b52501465250c80e1adf`.

## Modifications made on 2026-11-10

- Renamed the skill to `anthropic-fs-earnings-analysis`, added the t3OS finance category, and rewrote runtime assumptions to use only exposed, authorized tools.
- Added engagement, jurisdiction, currency, evidence, missing-data, review, and artifact-validation requirements.
- Namespaced bundled skill references, retained required Markdown reference resources, and removed unavailable Office, managed-runtime, example-workbook, and recalculation-script assumptions.
- Outputs remain drafts. Posting, payment, trades, filings, onboarding approval, publication, and sending are outside this template's authority.

## Included reference resources

- [references/best-practices.md](references/best-practices.md) from `plugins/agent-plugins/earnings-reviewer/skills/earnings-analysis/references/best-practices.md` (blob `3684a189ea38230ffc195e47a18a4893e2caeb37`).
- [references/report-structure.md](references/report-structure.md) from `plugins/agent-plugins/earnings-reviewer/skills/earnings-analysis/references/report-structure.md` (blob `0dfdb2be551b68dc828ef0526f3b59e1dcf399ce`).
- [references/workflow.md](references/workflow.md) from `plugins/agent-plugins/earnings-reviewer/skills/earnings-analysis/references/workflow.md` (blob `7c170e5e2d4783c231d2313650aacebb625c0fe8`).

- Changed the source's publication instruction to preparing a review-ready draft under an authorized review and distribution workflow.

## Verification boundary

The repository checks catalog loading, provenance, and text-resource integrity. Runtime package availability, source-system access, generated artifacts, recalculation, rendering, accounting judgments, and deployment remain separate checks for the configured agent and engagement.
