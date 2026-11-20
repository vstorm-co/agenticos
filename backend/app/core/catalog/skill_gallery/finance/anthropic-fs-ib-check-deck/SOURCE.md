# Source and modifications

This skill is adapted from Anthropic's anthropics/financial-services repository, pinned to commit `60565064557ca77b12f62aa7877f365d111c129d`. Original material is licensed under Apache License 2.0; the complete license is included in [LICENSE.txt](LICENSE.txt). This is a t3OS adaptation, not an Anthropic service or a promise that its connectors, subagents, or runtime are installed.

## Upstream skill copies

- [plugins/agent-plugins/pitch-agent/skills/ib-check-deck/SKILL.md](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/pitch-agent/skills/ib-check-deck/SKILL.md) — blob `a9a1b59c5e2ed37eccfa4bb1fe2e5b4aa4a71730`.

## Modifications made on 2026-11-10

- Renamed the skill to `anthropic-fs-ib-check-deck`, added the t3OS finance category, and rewrote runtime assumptions to use only exposed, authorized tools.
- Added engagement, jurisdiction, currency, evidence, missing-data, review, and artifact-validation requirements.
- Namespaced bundled skill references, retained required Markdown reference resources, and removed unavailable Office, managed-runtime, example-workbook, and recalculation-script assumptions.
- Outputs remain drafts. Posting, payment, trades, filings, onboarding approval, publication, and sending are outside this template's authority.

## Included reference resources

- [references/ib-terminology.md](references/ib-terminology.md) from `plugins/agent-plugins/pitch-agent/skills/ib-check-deck/references/ib-terminology.md` (blob `9d503181b2d4276c653c3514890d83c68a1b2154`).
- [references/report-format.md](references/report-format.md) from `plugins/agent-plugins/pitch-agent/skills/ib-check-deck/references/report-format.md` (blob `432162324b5bd9a5b1547a7e313f15c4e3ee0adc`).

## Runtime packaging changes

- `plugins/agent-plugins/pitch-agent/skills/ib-check-deck/scripts/extract_numbers.py`: Optional upstream executable helper or dependency manifest replaced by self-contained t3OS calculation, extraction, and verification instructions; no executable runtime is installed by a skill.

## Verification boundary

The repository checks catalog loading, provenance, and text-resource integrity. Runtime package availability, source-system access, generated artifacts, recalculation, rendering, accounting judgments, and deployment remain separate checks for the configured agent and engagement.
