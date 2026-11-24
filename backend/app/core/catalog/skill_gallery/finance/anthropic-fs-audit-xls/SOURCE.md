# Source and modifications

This skill is adapted from Anthropic's anthropics/financial-services repository, pinned to commit `60565064557ca77b12f62aa7877f365d111c129d`. Original material is licensed under Apache License 2.0; the complete license is included in [LICENSE.txt](LICENSE.txt). This is a t3OS adaptation, not an Anthropic service or a promise that its connectors, subagents, or runtime are installed.

## Upstream skill copies

- [plugins/agent-plugins/earnings-reviewer/skills/audit-xls/SKILL.md](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/earnings-reviewer/skills/audit-xls/SKILL.md) — blob `a2cae1d11c5e6704b95623a0ffeec8863ef1b8c2`.
- [plugins/agent-plugins/gl-reconciler/skills/audit-xls/SKILL.md](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/gl-reconciler/skills/audit-xls/SKILL.md) — blob `a2cae1d11c5e6704b95623a0ffeec8863ef1b8c2`.
- [plugins/agent-plugins/model-builder/skills/audit-xls/SKILL.md](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/model-builder/skills/audit-xls/SKILL.md) — blob `a2cae1d11c5e6704b95623a0ffeec8863ef1b8c2`.
- [plugins/agent-plugins/month-end-closer/skills/audit-xls/SKILL.md](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/month-end-closer/skills/audit-xls/SKILL.md) — blob `a2cae1d11c5e6704b95623a0ffeec8863ef1b8c2`.
- [plugins/agent-plugins/pitch-agent/skills/audit-xls/SKILL.md](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/pitch-agent/skills/audit-xls/SKILL.md) — blob `a2cae1d11c5e6704b95623a0ffeec8863ef1b8c2`.
- [plugins/agent-plugins/statement-auditor/skills/audit-xls/SKILL.md](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/statement-auditor/skills/audit-xls/SKILL.md) — blob `a2cae1d11c5e6704b95623a0ffeec8863ef1b8c2`.

## Modifications made on 2026-11-10

- Renamed the skill to `anthropic-fs-audit-xls`, added the t3OS finance category, and rewrote runtime assumptions to use only exposed, authorized tools.
- Added engagement, jurisdiction, currency, evidence, missing-data, review, and artifact-validation requirements.
- Namespaced bundled skill references, retained required Markdown reference resources, and removed unavailable Office, managed-runtime, example-workbook, and recalculation-script assumptions.
- Outputs remain drafts. Posting, payment, trades, filings, onboarding approval, publication, and sending are outside this template's authority.

## Verification boundary

The repository checks catalog loading, provenance, and text-resource integrity. Runtime package availability, source-system access, generated artifacts, recalculation, rendering, accounting judgments, and deployment remain separate checks for the configured agent and engagement.
