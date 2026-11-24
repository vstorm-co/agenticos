# Anthropic finance agents and accounting-firm skills for t3OS

This opt-in catalog pack ports Anthropic's ten released financial-services agent templates to t3OS and adds five accounting and advisory roles adapted from the community Agency Agents repository. It contains 15 agent templates and 43 skills: 31 financial-services skills, eight general finance skills, three small-business accounting workflows, and one t3OS engagement-context skill.

These are maintained t3OS adaptations. They are repository templates, not a live connection to either upstream repository. Installing a template creates an editable organization-owned draft and copies its skills. Subsequent upstream commits or catalog deployments do not overwrite those installed copies.

## Sources checked on 10 November 2026

| Source | Pinned commit | Upstream commit date (UTC) | Included content |
|---|---|---|---|
| [Anthropic financial-services](https://github.com/anthropics/financial-services/tree/60565064557ca77b12f62aa7877f365d111c129d) | `60565064557ca77b12f62aa7877f365d111c129d` | 28 October 2026 | All ten first-party agent plugins and 31 unique supporting skills |
| [Anthropic knowledge-work-plugins](https://github.com/anthropics/knowledge-work-plugins/tree/e605d8ddbfb688da57dfaaceebd93f12a64ef1d3) | `e605d8ddbfb688da57dfaaceebd93f12a64ef1d3` | 9 November 2026 | Eight finance skills; AP processing, invoice follow-up and cash-flow snapshot skills |
| [Agency Agents](https://github.com/msitarzewski/agency-agents/tree/8ae6164602c95ca78828b148b9052460ee426885) | `8ae6164602c95ca78828b148b9052460ee426885` | 9 November 2026 | Five accounting and financial-advisory roles |

Anthropic [announced its ten finance-agent templates on 5 May 2026](https://www.anthropic.com/news/finance-agents). Agency Agents is an independent community project, not an Anthropic release. Its main finance prompts in this pack were last edited on 11 April 2026; the AP prompt was last edited on 5 October 2026 UTC (6 October in Singapore). Repository freshness does not establish that a prompt's tax or regulatory assumptions are current.

Every adapted folder includes `SOURCE.md` with its exact upstream paths and changes, plus the full applicable license. The two JSON source inventories record the complete mapping. `manifest.json` lists the actual installable agent and skill keys.

## Agents

| Origin | Role | Use and scope |
|---|---|---|
| Anthropic | Month-End Closer | Close dependencies, accruals, roll-forwards, draft adjustments and variance commentary |
| Anthropic | GL Reconciler | General-ledger/subledger reconciliation, break investigation and evidence trails; fund/NAV procedures only where applicable |
| Anthropic | KYC Screener | Entity-document review, missing-evidence lists and escalation preparation; screening requires approved rules and real screening data |
| Anthropic | Statement Auditor | Fund LP capital-account statement and NAV-pack tie-out; this is not a general statutory-audit opinion |
| Anthropic | Valuation Reviewer | Methodology, assumptions, comparable valuations and sensitivity review |
| Anthropic | Model Builder | Financial-model construction and validation from supplied or connected evidence |
| Anthropic | Earnings Reviewer | Earnings documents, changes in financial performance and model implications |
| Anthropic | Market Researcher | Evidence-based issuer and sector research |
| Anthropic | Meeting Prep Agent | Client and counterparty briefing preparation |
| Anthropic | Pitch Agent | Target/comparable research and draft pitch materials |
| Agency Agents | Bookkeeper & Controller | Bookkeeping preparation, reconciliations, close controls and financial statements |
| Agency Agents | Accounts Payable | Invoice evidence, coding proposals, duplicate and matching checks, and proposed payment batches |
| Agency Agents | FP&A Analyst | Budget/actual analysis, forecasts and management reporting |
| Agency Agents | Financial Analyst | Financial analysis, cash-flow scenarios and advisory working papers |
| Agency Agents | Tax Strategist | Jurisdiction-specific research and preparation from current primary sources and client facts |

For a general accounting firm, start with Month-End Closer, GL Reconciler, Bookkeeper & Controller, Accounts Payable and FP&A Analyst. Add Tax Strategist once engagement jurisdiction and tax scope are specified. The investment/research agents are available for advisory engagements; installing every role is optional.

The financial-services agents preserve the responsibilities of the upstream workflows but use t3OS capability bindings. Upstream managed-agent manifests, callable subagent IDs, placeholder MCP URLs and deployment scripts are not t3OS configurations. A template cannot know organization-specific published-agent UUIDs, so these ports perform their review stages sequentially unless an operator explicitly wires published specialists into a t3OS coordinator.

## Skills and resources

The skills live under `backend/app/core/catalog/skill_gallery/finance/`, so they are opt-in and are not automatically seeded into every organization. Their names distinguish the source:

- `anthropic-fs-*`: 31 financial-services skills, including accrual scheduling, roll-forwards, GL reconciliation, break tracing, workbook review/authoring, KYC document parsing and financial-model procedures.
- `anthropic-finance-*`: journal entry, journal-entry preparation, reconciliation, financial statements, variance analysis, close management, SOX testing and audit support.
- `anthropic-smb-*`: AP processing, invoice follow-up and cash-flow snapshot workflows.
- `t3-accounting-engagement`: shared engagement scope, evidence and review conventions.

All supplementary files are UTF-8 resources because the t3OS skill loader reads resources as text. Required reference documents are packaged locally. Binary templates and absent upstream helpers are not silently assumed to exist: the adapted instructions identify the inputs and execution environment needed to produce the corresponding outputs.

SOX testing and audit-support procedures apply only to an engagement that actually requires that framework. US GAAP, tax forms, thresholds and source examples do not become the default for Singapore or other jurisdictions. Set the entity, period, currency, accounting framework, tax jurisdiction and review thresholds from the engagement; verify current rules using the responsible authority's primary sources.

## Install and activate

See [INSTALL.md](INSTALL.md) for the direct installer, authentication requirements, read-only planning, selective installation and recovery behavior.

There are two installation paths:

1. **After deploying this repository change**, choose the new templates in t3OS's finance catalog. The existing template installer resolves and installs the referenced gallery skills and creates a draft.
2. **Before a platform redeploy**, use the included installer against an explicitly selected organization. It reads this checked-out pack and the existing t3OS REST APIs. It creates missing skills/resources and draft agents; it refuses conflicts with edited copies.

For either path, select the target model profile, attach the client's knowledge and context, configure the real accounting/data connectors, and verify any artifact workspace. Review each draft before publishing a version. Creating templates or installing this pack does not connect an ERP, create screening credentials, provision a sandbox, or grant posting/payment/filing permissions.

### Workbooks, PDFs and OCR

The core `code_execution` capability is not a full document workstation. Creating and recalculating Excel workbooks requires an execution-enabled sandbox or a connected artifact service with the necessary libraries. The repository's `workbench` runtime definition includes `openpyxl`, `pandas`, document libraries and LibreOffice, but an operator must attach and verify a running instance.

t3OS also has an OCR-capable ingestion path: the backend Dockerfile installs Tesseract with English and Polish language packs. OCR behavior still depends on the collection parser configuration and deployed image. Language support, a successful extraction and source-document fidelity must be checked on representative client documents. A copied skill does not install an OCR engine or prove a particular deployment is configured for it.

When a required connector, workbook template, calculation engine or OCR facility is unavailable, the agent must state the missing dependency and produce the supported intermediate output. It must not claim it created a workbook, screened an entity, posted a journal, paid an invoice or completed a filing without the corresponding tool result and authority.

## Validation

The pack's offline check validates manifest paths, frontmatter, resources and skill bindings. The installer tests exercise wrong-organization refusal, dry-run behavior, idempotency, conflict handling and recovery after partial resource creation. The repository's existing catalog tests validate the shipped template and skill formats; the skill-count assertion is updated from 97 to 140.

Run the narrow application checks from a complete checkout with the repository's pinned Python environment:

```bash
cd backend
uv run pytest tests/test_agent_templates.py tests/test_skills.py::TestTheGalleryOnDisk tests/test_agent_registry.py::TestTheShippedTemplatesOnDisk -q
```

Structural validation does not establish accounting accuracy or end-to-end tool availability. Before using client data, exercise the selected roles on a representative ledger, invoice set or model with known expected results, and review the evidence and unresolved exceptions.

## Updating the pack

Compare a proposed upstream commit with the pinned source paths, review changes in accounting scope, resources, connector requirements and licenses, then update the adapted content and source inventories together. Re-run the catalog and installer checks. An organization can compare the new draft with its edited copy before adopting changes; there is no automatic upstream overwrite.

The source material is Apache-2.0 for the selected Anthropic content and MIT for Agency Agents. The source inventories, folder-level licenses, root `NOTICE`, `licenses/components.toml` and `THIRD_PARTY_NOTICES.md` record attribution and modifications. Partner plugins and unrelated document-skill bundles are not included.
