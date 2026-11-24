# Source and modifications

This template adapts Anthropic's [model-builder](https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/plugins/agent-plugins/model-builder/agents/model-builder.md) at commit `60565064557ca77b12f62aa7877f365d111c129d` (source blob `a5927e52436452eb54bf060609acbc764b3565fa`). The complete Apache License 2.0 is included in [LICENSE.txt](LICENSE.txt).

## Modifications made on 2026-11-10

- Converted the source agent prompt into a reusable t3OS catalog template named **Anthropic Model Builder**, without client-specific branding.
- Replaced Claude-specific tool declarations, connector placeholders, runtime assumptions, and implied subagent dispatch with available t3OS capabilities and explicit sequential phases.
- Bound the source agent's bundled skills to deduplicated `anthropic-fs-` gallery entries. No managed-agent service, model, external account, or isolated worker is provisioned.
- Added engagement, jurisdiction, period, currency, evidence, review, and artifact fallback requirements. The original workflow's scope remains explicit, including fund NAV and LP statements where applicable.
- Suggested collection and sandbox attachment while leaving resource-specific capability configuration to the actual operator binding.

## Bound skill keys

- `finance/anthropic-fs-3-statement-model`
- `finance/anthropic-fs-audit-xls`
- `finance/anthropic-fs-comps-analysis`
- `finance/anthropic-fs-dcf-model`
- `finance/anthropic-fs-lbo-model`
- `finance/anthropic-fs-xlsx-author`

## Operational status

This is an installable template definition. It is not an already created or published agent record and does not establish that connectors, runtimes, source data, or review workflows are configured. Posting, payments, trades, filings, onboarding approval, publication, and sending are not authorized by this template.
