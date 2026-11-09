---
name: artifact-pages
description: "Design a useful published App or report for readers outside the chat. Use for information hierarchy, interaction and visual verification; the publishing tool owns its runtime contract."
category: design
---

# Make the result useful before making it elaborate

Choose the medium for the person's question: prose for a direct answer, a table for exact comparisons, a chart for a quantitative pattern, and an interactive visual when changing a control teaches something. A reusable App or deck needs an audience and purpose beyond this chat.

Lead with the conclusion or the decision. Build a visible hierarchy, use restrained color, readable type and consistent spacing, and fit both phone and desktop. Label units, source evidence and uncertainty. Keep controls relevant and make their consequences visible. Prefer one clear idea per view or slide over a dense dashboard.

Use the active tool description as the authority for input format, supported libraries, runtime limitations and publication. Do not infer another environment or copy unsupported API parameters from an example. Reuse the available templates when they fit, adapting content and composition to the task.

The optional resource `references/design-recipes.md` contains detailed design examples and template guidance; read the section needed for the chosen medium rather than loading every recipe. Current tool contracts win over older implementation examples.

For an App, define the job, primary action and audience before layout. Design loading, empty, error and success states. Keep navigation predictable, respect the audience's access and verify the published page separately from a local preview. Persistent data and external actions require actual supported connections; a static mockup must say it is a mockup.

Render and inspect the result. Check readability, overflow, contrast, interactions, sources and the intended audience's access. Repair concrete defects before presenting it. Link the real artifact and describe what the person can try; do not call an unrendered draft verified.
