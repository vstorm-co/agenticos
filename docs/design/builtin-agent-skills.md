# Built-in operational skills

The starter agents need procedures grounded in this deployment's contracts, not
promises of tools their current run cannot use. Nine bundled skills cover agent
configuration, workflows, automation, skill authoring, Context, Tables, durable
work, document production and evidence-based research. Both starter templates
also bind the existing App, visual and presentation/storyline/review skills.
The same AgenticOS template supplies new console agents, excluding its explicitly
restricted computer/browser/coding capabilities as before.

## Upgrade behavior

A release fingerprint includes the complete bundled library and resources, as
well as the template and deployment-dependent capability configuration. Opening
the console refreshes shipped agents through the existing organization install
lock. A new agent created from the starter also synchronizes built-ins under that
lock using the organization's actual owner as the platform installer.

Synchronization installs a never-delivered skill, updates an untouched copy and
preserves edited/untracked copies. Immutable `skill.installed` audit receipts
identify retired skills, even after their rows are deleted. Automatic refresh
skips them; an explicit seed command retains its deliberate restore behavior.
The Skills list does not install resources as a read side effect. Model changes
remain independent of protected prompt/tool/skill fields. Existing user-authored
agents are not rewritten. Deployments with no console visit and no new starter
agent creation can still use `agenticos cmd seed-skills` for eager installation.

Descriptions are always visible to the model when bound; full procedures and
resources load progressively. Binding this set is a finite context cost, not
free context. The core prompts route to relevant skills and describe completion,
question-tool use, delegation, background lifetimes, authority and verification.

## Tool gaps addressed

Platform MCP now reads/edits skills and adds text resources, discovers/reads/
creates/edits Context, and binds `context_ids` when creating or editing a draft.
These operations use the existing public API, caller scopes and normal write
approvals. Omitted update fields retain existing values. Context file edits affect
the next run; a new agent binding requires publication. The richer authoring
procedure therefore has real operations behind it.

Apps and Visuals instructions distinguish an HTML rendering from a native file.
The document-production skill supplies a LaTeX starting layout and build/render
procedures, not a compiler or presentation runtime. It requires probing the
actual workspace and delivering honest source-only output when execution or
rendering is unavailable. Architect gains Apps and Charts alongside its existing
visual and sandbox capabilities.

## Research and provenance

Reviewed primary-source skill examples:

- [OpenAI skill creator](https://github.com/openai/skills/blob/main/skills/.system/skill-creator/SKILL.md): selection descriptions, concise procedures and progressive resources.
- [Anthropic presentation skill](https://github.com/anthropics/skills/blob/main/skills/pptx/SKILL.md): distinction between editable presentation structure and rendered visual checks.
- [Anthropic frontend design skill](https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md): intentional composition grounded in the actual subject.

The shipped content is independently written for AgenticOS. No third-party
scripts, templates or assumed bundled dependencies are copied; in particular,
source-available document tooling is not treated as a license to redistribute it.
The existing AgenticOS design system remains authoritative for Apps and visuals.

## Acceptance

Real PostgreSQL/MCP tests exercise old-organization installation, unchanged
refresh, edited skills, retirement, new default-agent bindings, Context and skill
resource writes, binding preservation, tenant isolation and narrowed-key refusal.
Unit tests check catalog validity, tool transport/approval metadata and release
changes for library updates. Existing prompt/model/pending-draft preservation
regressions remain in scope. These deterministic checks do not establish that an
LLM will choose every skill or produce a polished document on every request.

The five [manual prompts](agenticos-test-prompts.md) exercise those model-level
behaviors together. Record the actual run/conversation links, artifacts, selected
skills, tools, failures and unnecessary questions before tuning instructions.
