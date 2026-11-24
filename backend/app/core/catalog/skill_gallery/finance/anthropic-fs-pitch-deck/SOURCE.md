# Source and modifications

This skill is adapted from Anthropic's anthropics/financial-services repository, pinned to commit `60565064557ca77b12f62aa7877f365d111c129d`. Original material is licensed under Apache License 2.0; the complete license is included in [LICENSE.txt](LICENSE.txt). This is a t3OS adaptation, not an Anthropic service or a promise that its connectors, subagents, or runtime are installed.

## Upstream skill copies

- [plugins/agent-plugins/pitch-agent/skills/pitch-deck/SKILL.md](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/pitch-agent/skills/pitch-deck/SKILL.md) — blob `830f9f11f8ff29d982961a79ca37d0d05cd8ea67`.

## Modifications made on 2026-11-10

- Renamed the skill to `anthropic-fs-pitch-deck`, added the t3OS finance category, and rewrote runtime assumptions to use only exposed, authorized tools.
- Added engagement, jurisdiction, currency, evidence, missing-data, review, and artifact-validation requirements.
- Namespaced bundled skill references, retained required Markdown reference resources, and removed unavailable Office, managed-runtime, example-workbook, and recalculation-script assumptions.
- Outputs remain drafts. Posting, payment, trades, filings, onboarding approval, publication, and sending are outside this template's authority.

## Included reference resources

- [reference/calculation-standards.md](reference/calculation-standards.md) from `plugins/agent-plugins/pitch-agent/skills/pitch-deck/reference/calculation-standards.md` (blob `d62a761ac7ee3d464c7d50d70e2b30f770a4c216`).
- [reference/formatting-standards.md](reference/formatting-standards.md) from `plugins/agent-plugins/pitch-agent/skills/pitch-deck/reference/formatting-standards.md` (blob `2352c72e92cfb28b03d870a53411b921739ef0af`).
- [reference/slide-templates.md](reference/slide-templates.md) from `plugins/agent-plugins/pitch-agent/skills/pitch-deck/reference/slide-templates.md` (blob `bac14319ef16a9a031dde9adb6dd37e466d8d26d`).
- [reference/xml-reference.md](reference/xml-reference.md) from `plugins/agent-plugins/pitch-agent/skills/pitch-deck/reference/xml-reference.md` (blob `9c611a25750d6f6aa336e3190402518b6199724e`).

## Verification boundary

The repository checks catalog loading, provenance, and text-resource integrity. Runtime package availability, source-system access, generated artifacts, recalculation, rendering, accounting judgments, and deployment remain separate checks for the configured agent and engagement.
