# Source and adaptation

Anthropic official source, adapted for t3OS; this adaptation is not an Anthropic-endorsed integration.

- Repository: [anthropics/knowledge-work-plugins](https://github.com/anthropics/knowledge-work-plugins)
- Pinned commit: `e605d8ddbfb688da57dfaaceebd93f12a64ef1d3`
- Source: [finance/skills/reconciliation/SKILL.md](https://github.com/anthropics/knowledge-work-plugins/blob/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3/finance/skills/reconciliation/SKILL.md)
- Source SHA-256: `aa17e90539f4d4d84130c910c7f527236bfaa71977c4c03493c8e8e515ddeea6`
- License: Apache-2.0; the complete upstream license is in [LICENSE](LICENSE).
- Adapted for t3OS on 2026-11-10.

## Changes

- Renamed the skill to a collision-safe t3OS gallery key, replaced plugin-only metadata, and mapped upstream slash aliases to natural requests or available installed skills.
- Adapted the substantive finance methodology and examples; localized connector references and made operations conditional on actual authorized read schemas.
- Converted operational posting, notification and close actions into draft proposals or tracking of evidenced authorized-owner completion; proposals do not establish external execution.
- Added engagement isolation, evidence, framework applicability and preparation-only boundaries; US/SOX examples are conditional and must be checked against the current engagement.
- Documented read_skill/read_skill_resource loading and optional artifact runtime; no Claude plugin filesystem or connector installation is assumed.

The pinned source records provenance, not live regulatory guidance or a connected account. References to frameworks, tax rules, connector capabilities and example thresholds must be checked against the engagement and currently exposed tools. The content prepares evidence and draft outputs for human review; installing it does not connect applications, grant authority or publish an agent.

## Bundled resource mapping

| Local resource | Pinned upstream source |
|---|---|
| `CONNECTORS.md` | [finance/CONNECTORS.md](https://github.com/anthropics/knowledge-work-plugins/blob/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3/finance/CONNECTORS.md) |
| `LICENSE` | [finance/LICENSE](https://github.com/anthropics/knowledge-work-plugins/blob/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3/finance/LICENSE) |
