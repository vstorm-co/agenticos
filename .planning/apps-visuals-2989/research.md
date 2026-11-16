# Apps and Visuals skill research — 2026-11-13

Issue: #2989. This is implementation research for the shipped AgenticOS catalog, not an installation of third-party agent instructions.

## Sources inspected

| Primary source | Pinned revision | Useful contribution | Adaptation for AgenticOS |
| --- | --- | --- | --- |
| [Anthropic frontend-design](https://github.com/anthropics/skills/blob/2c5958ecac7cee2b583967a2c4981d0f4a75c579/skills/frontend-design/SKILL.md) | `2c5958e` | Subject-specific composition, deliberate type scale, meaningful hierarchy and restrained motion. | Respect supplied branding. Use available system fonts; keep controls semantic and functional. |
| [Anthropic web-artifacts-builder](https://github.com/anthropics/skills/blob/2c5958ecac7cee2b583967a2c4981d0f4a75c579/skills/web-artifacts-builder/SKILL.md) | `2c5958e` | Separate the build from a self-contained deliverable. | Build tooling is optional and must actually exist. Published HTML cannot rely on a development server or CDN. Render verification remains required here. |
| [Anthropic algorithmic-art](https://github.com/anthropics/skills/blob/2c5958ecac7cee2b583967a2c4981d0f4a75c579/skills/algorithmic-art/SKILL.md) | `2c5958e` | Reproducible generative geometry, parameter exploration and a useful initial composition. | Native Canvas/SVG and seeded randomness; no assumed p5.js download. Keep artistic patterns distinct from measured data. |
| [Anthropic canvas-design](https://github.com/anthropics/skills/blob/2c5958ecac7cee2b583967a2c4981d0f4a75c579/skills/canvas-design/SKILL.md) | `2c5958e` | Space, scale and image-led composition as information. | Choose raster, vector or an interactive view by the requested output. Avoid a long mandatory design manifesto before every small task. |
| [Taste Skill](https://github.com/Leonxlnx/taste-skill/blob/f6b76575f949707b4e3c37cd86cb44b0b98643e8/skills/taste-skill/SKILL.md) | `f6b7657` | Audience-specific layout families, reference-guided composition and browser checks. | Keep an existing brand; avoid mandatory remote photography, a new website scaffold or effects on every output. |
| [Vercel Web Interface Guidelines](https://github.com/vercel-labs/agent-skills/blob/1a2c79d4e6c4a2283dc2c614b6538cbe1ed5ca62/skills/web-design-guidelines/SKILL.md) | `1a2c79d` | Concrete accessibility and interaction review rather than subjective approval. | Focus, labels, keyboard access, reduced motion and error states belong in the local verification recipe. |
| [UI UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/6ae86f61f520d6ca229d2f40e070410638c908c5/.claude/skills/ui-ux-pro-max/SKILL.md) | `6ae86f6` | Match one design concern to the actual platform and prioritize accessibility, input and feedback. | A short task-to-recipe index replaces a large always-loaded style database and external CLI. |

The fetched design skills carry Apache-2.0 (Anthropic design folders) or MIT (Taste Skill and UI UX Pro Max) licenses. The implementation will use original AgenticOS instructions and examples, with these links recording design provenance. No upstream code or asset bundle is vendored; any later copying requires its own license/notice review.

## Runtime evidence

- `artifacts.publish_artifact` publishes versioned HTML/Markdown with stable names. Isolated pages have no arbitrary network access. Dynamic table data and workflow actions use explicit, permission-checked bindings/actions.
- Apps use the served `agenticos-3` assets; Visuals use the served `agenticos-2` assets. Instructions must not conflate their helper APIs.
- Visuals accept HTML, SVG or Mermaid. HTML supports the locally served Chart.js, d3, three.js and map kits. Images use the tool's admitted image mechanism.
- A CDN, remote font, guessed fetch endpoint or unbundled React import is not a working deliverable. Native HTML/SVG examples need no package installation.
- `read_skill_resource` loads a selected reference/template; the body should not inline every example into the prompt.
- `SkillService.refresh_from_library` fingerprints content and resource files. Untouched copies refresh as a version/proposal; edited or untracked copies are protected by default. A bound skill may need a check before a proposal goes live.

## Planned original resources

Apps: a design/interaction playbook, a concise runtime checklist, an editorial evidence brief and a decision workbench with real state transitions. Keep the existing report, dashboard and live-table recipes.

Visuals: a medium/encoding playbook, parameter and animation guidance, an annotated comparison lab and a seeded generative composition. Keep the existing maps, 3D, calculator and explainer recipes.

Both: accessible controls, honest data/units, keyboard/reset behavior, mobile layout, explicit failure/empty states and a rendered verification checklist. Examples use labelled demonstration data and original graphics.

## Validation plan

1. Verify each new template with deterministic interactions at desktop and phone widths; check console errors, unexpected network requests and overflow.
2. Publish Apps through the application service and inspect their actual isolated pages. Draw Visuals through the real tool contract and inspect the same served library paths used by chat.
3. Exercise catalog refresh on an untouched copy and an edited copy, including resource changes and proposal/version behavior.
4. Preserve model/profile choices and keep examples/long references lazy. Report template verification separately from any model-based quality comparison.
5. Give the maintainer the complete local application and test scenarios before release; publication remains on hold.

## Preview loading verification

Modern Web Guidance `motion` informed compositor-only opacity reveal and reduced-motion handling. Loading pulse is finite and decorative; layout footprint remains reserved. Real-browser test delays the renderer endpoint, captures the skeleton, releases it and verifies removal on the renderer completion event. Image previews reveal on decode/load rather than an arbitrary timer. Screenshots are kept outside the repository under the Codex visualizations directory.
