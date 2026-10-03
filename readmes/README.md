# README proposals

**Start with [11 · Combined](11-combined.md)**, the candidate for the root README. It keeps the current README's positioning and product tour and adds the visual gallery's recording-first opening and captioned screen grid. It also has a "Find your path" section with collapsible parts for decision makers, security reviewers, developers and teams looking for a first task, plus a summary of what ships and where it stops.

The ten alternatives below were the input, one per reader. Each one opens on GitHub with its images, so you can judge it as a visitor would. None replaces the root `README.md` yet. Pick what works, and the chosen ideas get merged into the real README and its three translations.

| # | Proposal | Written for | Idea |
|---|---|---|---|
| 11 | [**Combined**](11-combined.md) | Everyone | Current README + gallery + a path per reader, in one page |
| 01 | [Product tour plus](01-product-tour-plus.md) | Everyone | The current README, extended with an "at a glance" table, annotated screens, the full capability list and a limits section |
| 02 | [For decision makers](02-for-decision-makers.md) | CEO, head of operations | The four questions nobody can answer today, how it fits into the company, what it takes and how to start |
| 03 | [Developer first](03-developer-first.md) | Engineers | Install, architecture table, capabilities, API, models, retrieval, and what to know before building on it |
| 04 | [Security review](04-security-review.md) | IT and security | Every outbound destination, identity and access, runtime controls, secrets and isolation, and what stays with your IT |
| 05 | [Use-case gallery](05-use-case-gallery.md) | Teams looking for a first task | Led by the 29 tutorials, grouped by team, with screens between the tables |
| 06 | [Minimal](06-minimal.md) | Skimmers | One screen: hero image, three bullets, one command, links |
| 07 | [Feature reference](07-feature-reference.md) | Evaluators comparing tools | Everything that ships, in tables, with a limits table at the end |
| 08 | [A week with AgenticOS](08-a-week-with-agenticos.md) | Non-technical readers | An illustrative week in an invented company, Monday to Friday, told through real screens |
| 09 | [Is it a fit?](09-is-it-a-fit.md) | Anyone choosing a platform | When to choose it, when to look elsewhere, how it compares, and how to evaluate it on one task |
| 10 | [Visual gallery](10-visual-gallery.md) | Visual browsers | The recording first, then a captioned grid of screens, the architecture and the integrations |

## Shared material

- **Screens:** the fourteen PNG captures in `docs/assets/screens/light/`, the OSS Launch Planner recording and the integrations SVG, all from this pull request.
- **New graphics** in `readmes/assets/`, rendered from the AgenticOS pre-sales deck. All are 1600 × 900 WebP, under 120 KB each. Each states facts checked against `docs/` and the code at f87f30e:
  - Annotated builder, dashboard and approvals overviews.
  - Company architecture, organisation model and the RAG pipeline.
  - The 26 capabilities, eight surfaces, 27 providers and security layers.
  - Sovereignty options, sizing, the 29 tutorials, and the "not today" limits.
- **Facts used across proposals:**
  - 26 registered capabilities (`docs/reference/capabilities.md`).
  - 27 providers (`docs/models.md`).
  - Five sync connectors (`backend/app/services/rag/connectors/__init__.py`).
  - Six roles (`docs/permissions.md`).
  - Eight surfaces (`docs/channels.md`).
  - 4 vCPU and 8 GB (`docs/deploy.md`).
  - 29 tutorials, 24 with a reference run (`docs/use-cases.md`).

## Deliberately left out

Things the docs or code do not support, so no proposal claims them:

- Native MFA, SAML or SCIM.
- Per-user API keys: `X-API-Key` is documented but not wired to a route.
- Reranking or hybrid search.
- Mirrored source ACLs.
- Kubernetes or multi-host scaling.
- Zero-downtime upgrades.
- A KMS-backed vault.
- Sandbox egress control.
- Strict budgets under parallel runs.
- An installable browser-use.

## Before one becomes the README

Paths here are relative to `readmes/` (`../docs/assets/...`, `assets/...`). Moving a proposal to the root means:

- Dropping the `../` from paths.
- Moving `readmes/assets/` under `docs/assets/`.
- Translating it into `README.pl.md`, `README.de.md` and `README.es.md`, as `scripts/check_docs_i18n.py` requires.
