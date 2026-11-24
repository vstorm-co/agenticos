# Source and modifications

This skill is adapted from Anthropic's anthropics/financial-services repository, pinned to commit `60565064557ca77b12f62aa7877f365d111c129d`. Original material is licensed under Apache License 2.0; the complete license is included in [LICENSE.txt](LICENSE.txt). This is a t3OS adaptation, not an Anthropic service or a promise that its connectors, subagents, or runtime are installed.

## Upstream skill copies

- [plugins/agent-plugins/earnings-reviewer/skills/xlsx-author/SKILL.md](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/earnings-reviewer/skills/xlsx-author/SKILL.md) — blob `0d757862a9257f69801adaf6f93e2bf70f8a7fe9`.
- [plugins/agent-plugins/gl-reconciler/skills/xlsx-author/SKILL.md](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/gl-reconciler/skills/xlsx-author/SKILL.md) — blob `0d757862a9257f69801adaf6f93e2bf70f8a7fe9`.
- [plugins/agent-plugins/kyc-screener/skills/xlsx-author/SKILL.md](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/kyc-screener/skills/xlsx-author/SKILL.md) — blob `0d757862a9257f69801adaf6f93e2bf70f8a7fe9`.
- [plugins/agent-plugins/model-builder/skills/xlsx-author/SKILL.md](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/model-builder/skills/xlsx-author/SKILL.md) — blob `0d757862a9257f69801adaf6f93e2bf70f8a7fe9`.
- [plugins/agent-plugins/month-end-closer/skills/xlsx-author/SKILL.md](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/month-end-closer/skills/xlsx-author/SKILL.md) — blob `0d757862a9257f69801adaf6f93e2bf70f8a7fe9`.
- [plugins/agent-plugins/pitch-agent/skills/xlsx-author/SKILL.md](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/pitch-agent/skills/xlsx-author/SKILL.md) — blob `0d757862a9257f69801adaf6f93e2bf70f8a7fe9`.
- [plugins/agent-plugins/statement-auditor/skills/xlsx-author/SKILL.md](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/statement-auditor/skills/xlsx-author/SKILL.md) — blob `0d757862a9257f69801adaf6f93e2bf70f8a7fe9`.
- [plugins/agent-plugins/valuation-reviewer/skills/xlsx-author/SKILL.md](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/valuation-reviewer/skills/xlsx-author/SKILL.md) — blob `0d757862a9257f69801adaf6f93e2bf70f8a7fe9`.

## Modifications made on 2026-11-10

- Renamed the skill to `anthropic-fs-xlsx-author`, added the t3OS finance category, and rewrote runtime assumptions to use only exposed, authorized tools.
- Added engagement, jurisdiction, currency, evidence, missing-data, review, and artifact-validation requirements.
- Namespaced bundled skill references, retained required Markdown reference resources, and removed unavailable Office, managed-runtime, example-workbook, and recalculation-script assumptions.
- Outputs remain drafts. Posting, payment, trades, filings, onboarding approval, publication, and sending are outside this template's authority.

## Verification boundary

The repository checks catalog loading, provenance, and text-resource integrity. Runtime package availability, source-system access, generated artifacts, recalculation, rendering, accounting judgments, and deployment remain separate checks for the configured agent and engagement.
