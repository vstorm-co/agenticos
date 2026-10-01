# README media and capture inventory

## Current README demo

- Video: https://github.com/user-attachments/assets/529c8a90-501e-45c7-81d1-0f8de7829953
- Upload reference: https://github.com/vstorm-co/agenticos/issues/168#issuecomment-5937226436
- Poster: `oss-launch-planner-poster.webp`, extracted at 24 seconds from the user-provided edited demo.
- Content: the Claude Code like agent prepares the OSS Launch Planner, the user changes its audience selection and creates a sharing link.
- The video is edited: waiting time is removed. Repository metrics are a snapshot, not live data.

The four root READMEs share this video and poster. Upcoming screenshots are visibly marked as
placeholders rather than using old UI captures or missing image paths. Each slot has a stable HTML
comment (`MEDIA: <id>`) to find it across translations. Capture matching light/dark pairs with the same
content and framing, then replace the corresponding blockquote with a theme-aware picture.

| Slot | Capture |
|---|---|
| `agent-builder` | Complete: demo agent instructions, selected model, published version and draft changes |
| `skills` | Complete: library and the artifact-pages procedure with instructions and templates |
| `context` | Complete: library and glossary content with linked mode for on-demand reading |
| `knowledge-bases` | Complete: personal and organization collections |
| `knowledge-collection` | Complete: vstorm collection with document name, processing status and chunk count |
| `mcp-connections` | Complete: connected server catalog including GitHub and Notion; no credentials shown |
| `artifacts` | Complete: library and the OSS Launch Planner from the demo |
| `run-detail` | The demo execution, tool calls and recorded cost |
| `approval` | Complete: actual pending execute action and decision controls |
| `routines` | Schedule, actual completed scheduled run and result |

Eight screenshot slots are complete; `run-detail` and `routines` remain pending.
The pair was supplied on 2026-10-01 at 110% browser zoom with the sidebar collapsed,
and stored as lossless WebP at the original 3502 × 2000 resolution.
Files: `light/agent-builder.webp` and `dark/agent-builder.webp`. The poster is a frame from the supplied video, not a new UI capture.
The Skills captures were supplied on 2026-10-01 and stored as lossless WebP at
3502 × 2000: `light/skills.webp`, `dark/skills.webp`, `light/skill-detail.webp`
and `dark/skill-detail.webp`. They show the library and the artifact-pages procedure in Preview.

The Context captures were supplied on 2026-10-01 and stored as lossless WebP at
3502 × 2000: `light/context.webp`, `dark/context.webp`, `light/context-detail.webp`
and `dark/context-detail.webp`. They show the library and the Glossary file in Preview,
with linked mode and the enabled setting visible.

The knowledge captures were supplied on 2026-10-01 and stored as lossless WebP at
3502 × 2000: `light/knowledge-bases.webp`, `dark/knowledge-bases.webp`,
`light/knowledge-collection.webp` and `dark/knowledge-collection.webp`. They show
the collection list and the vstorm document list with a completed processing status.

The MCP, Artifacts and Approval pairs were captured from the authenticated application on
2026-10-02 at 1751 × 1000, with the sidebar collapsed, and encoded as lossless WebP without
resizing or altering the UI. Files in both theme directories: `mcp-connections.webp`,
`artifacts.webp`, `artifact-detail.webp`, `approval.webp`.

The MCP view shows connected servers, not the tools enabled for a particular agent.
The OSS Launch Planner keeps its own dark styling in both application themes; its data is
explicitly labeled as a 1 October snapshot. Approval shows a real pending action; no approval
or rejection was performed to prepare the capture. Narrow preliminary captures are not committed.

The current Routines examples contain internal business instructions; a suitable demo capture
with a real completed scheduled run is still needed.

Previous UI screenshots, the old CSV demo and its poster/animation were removed from the repository.
The documentation and presentation use explicit placeholders until new captures are ready.
Earlier assets remain recoverable from Git history; do not reuse them for the refreshed interface.

## Placement and positioning

The README leads with the open-source agent layer for companies: shared agents, knowledge,
automation and control over deployment and models. Use AI agent harness and Claude Code-like
only where they explain the execution model or a concrete example. Do not label the product a platform
or imply live multiplayer sessions, absolute data isolation, model parity or guaranteed search rankings.

The main reading path shows the demo followed by a visible feature table: a short explanation beside
one linked screenshot per feature. Additional library and collection views and the pending run-detail
capture sit in a collapsed supplement. The Routines row keeps its explicit placeholder. Team access,
installation and deployment controls follow the gallery; terminology remains defined in the feature copy.
The layout takes inspiration from stablyai/orca, using AgenticOS copy and original product captures.

## Paths and video embedding

Use relative paths for repository images (`docs/assets/screens/...`) so the README can be reviewed
on a feature branch. Check light/dark picture rendering on GitHub when adding the new pairs.

Use the stable GitHub attachment URL for the video, not a local MP4 or a temporary signed redirect.
The current attachment is listed at the top. A ranged GET returned `206` with `video/mp4` on 2026-10-01.
GitHub's Markdown renderer retains the video and controls but may strip the poster attribute;
the README also offers explicit video and screenshot links.

An image nested inside a video does not replace a broken source in a browser that supports video.
Keep the independent screenshot link. Do not commit local video masters; GitHub hosts the uploaded video.
