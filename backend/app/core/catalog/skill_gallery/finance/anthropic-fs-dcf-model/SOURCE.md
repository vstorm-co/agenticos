# Source and modifications

This skill is adapted from Anthropic's anthropics/financial-services repository, pinned to commit `60565064557ca77b12f62aa7877f365d111c129d`. Original material is licensed under Apache License 2.0; the complete license is included in [LICENSE.txt](LICENSE.txt). This is a t3OS adaptation, not an Anthropic service or a promise that its connectors, subagents, or runtime are installed.

## Upstream skill copies

- [plugins/agent-plugins/model-builder/skills/dcf-model/SKILL.md](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/model-builder/skills/dcf-model/SKILL.md) — blob `cc17fc002b7e739d00e6b62c4c7a3a806b6f3f22`.
- [plugins/agent-plugins/pitch-agent/skills/dcf-model/SKILL.md](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/pitch-agent/skills/dcf-model/SKILL.md) — blob `cc17fc002b7e739d00e6b62c4c7a3a806b6f3f22`.

## Modifications made on 2026-11-10

- Renamed the skill to `anthropic-fs-dcf-model`, added the t3OS finance category, and rewrote runtime assumptions to use only exposed, authorized tools.
- Added engagement, jurisdiction, currency, evidence, missing-data, review, and artifact-validation requirements.
- Namespaced bundled skill references, retained required Markdown reference resources, and removed unavailable Office, managed-runtime, example-workbook, and recalculation-script assumptions.
- Outputs remain drafts. Posting, payment, trades, filings, onboarding approval, publication, and sending are outside this template's authority.

## Included reference resources

- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) from `plugins/agent-plugins/model-builder/skills/dcf-model/TROUBLESHOOTING.md` (blob `eb46365ca1a4264a73cc5796b216faad4307a323`).

## Runtime packaging changes

- `plugins/agent-plugins/model-builder/skills/dcf-model/requirements.txt`: Optional upstream executable helper or dependency manifest replaced by self-contained t3OS calculation, extraction, and verification instructions; no executable runtime is installed by a skill.
- `plugins/agent-plugins/model-builder/skills/dcf-model/scripts/validate_dcf.py`: Optional upstream executable helper or dependency manifest replaced by self-contained t3OS calculation, extraction, and verification instructions; no executable runtime is installed by a skill.

## Verification boundary

The repository checks catalog loading, provenance, and text-resource integrity. Runtime package availability, source-system access, generated artifacts, recalculation, rendering, accounting judgments, and deployment remain separate checks for the configured agent and engagement.
