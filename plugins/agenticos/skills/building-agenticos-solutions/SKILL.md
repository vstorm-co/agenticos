---
name: building-agenticos-solutions
description: Builds a complete AgenticOS solution from the user's own business case or a reusable resource bundle. Use for support, repository operations, onboarding and other requests combining agents, knowledge, skills, workflows, tables or test datasets.
---

# Build the user's outcome

Start with the deliverable, audience, authoritative sources, input events,
permitted effects and evidence of completion. The bundled examples are starting
points, not a closed catalog: any use case supported by discovered capabilities,
workflow nodes and integrations can be designed here.

1. Read `whoami` and `get_platform_context`. Discover existing resources before
   creating replacements. Read capability configurations, node contracts and
   connected tool contracts; never invent a node, tool, port or provider.
2. Choose the fewest mechanisms that meet the outcome. Use an agent for judgment,
   a workflow for deterministic coordination, a table for structured state, a
   knowledge base for retrieved documents, Context for standing facts and a skill
   for a procedure. A routine or watch is optional unattended work, not mandatory.
3. Resolve model and embedding dependencies with their discovery tools. Use
   `get_setup_link` when the person must enter credentials or approve OAuth,
   then rediscover the resource. No credentials belong in a manifest or graph.
4. Offer an existing solution or prepare a custom manifest using the schemas of
   `plan_solution`. Supply logical references between package agents and their
   Context, skills and knowledge. Workflow preparation may contain a new table
   and its placeholder UUID, exactly as the workflow preparation tool does.
5. Call `plan_solution` on the exact manifest. Review its resources, external
   references, permissions and private-draft effects with the user. Set unique
   resource names for another copy; a new installation key alone does not rename
   existing resources. Copy the returned hash to `expected_manifest_hash`.
6. `install_solution` creates all resources and its receipt in one transaction.
   The installation key belongs to this caller in this organization. Reuse the
   same key and manifest after an uncertain outcome; a different manifest is
   refused. Another manifest needs another key and suitable resource names.
7. Read every returned resource back. A replayed receipt records installation
   history, not readiness after later edits or deletion. Check workflow drafts,
   configure models if omitted, and test agents. Installation publishes, runs,
   indexes and schedules nothing.
8. Follow the release skill for quality checks and promotion. Sharing, ingestion,
   integration consent and unattended triggers are separate consequential actions.
   Report dependencies still missing rather than claiming a live solution.

Examples in this plugin's `solutions/`: `support.json`, `repository.json` and
`onboarding.json`. They include a standing policy, a procedure, a scored test
question, an agent and a typed intake workflow writing to its own table. Their
agents deliberately have no selected paid model. Choose an existing profile
before planning when a runnable agent is required. Add a knowledge base only
when its sources and embedding configuration are known.

A bundle is an installation contract, not a generic upgrade engine. To change
installed resources, read and edit them through their normal revision-aware
operations. Never overwrite an organization's later edits by reinstalling a
modified example. For a service without a suitable MCP tool, discover whether a
workflow HTTP step can use an existing vault reference before proposing new code.

A workflow calling a catalog agent must pin an already published version. A
draft-only bundle cannot supply that publication: install first, test and publish
the agent, then bind its exact version in the workflow draft. An inline agent
step is another supported design when the workflow should own that agent. Read
the node contract before choosing; do not invent a reference to a future version.
