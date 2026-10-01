# README media and capture inventory

## Original demo source

- Video: https://github.com/user-attachments/assets/529c8a90-501e-45c7-81d1-0f8de7829953
- Upload reference: https://github.com/vstorm-co/agenticos/issues/168#issuecomment-5937226436
- Poster: `oss-launch-planner-poster.webp`, extracted at 24 seconds from the user-provided edited demo.
- Content: the Claude Code like agent prepares the OSS Launch Planner, the user changes its audience selection and creates a sharing link.
- The video is edited: waiting time is removed. Repository metrics are a snapshot, not live data.

The four root READMEs share the shortened demo and animated preview described below. Upcoming screenshots are visibly marked as
placeholders rather than using old UI captures or missing image paths. Each slot has a stable HTML
comment (`MEDIA: <id>`) to find it across translations. Capture light-mode views with expanded navigation, then replace the corresponding blockquote
with a linked screenshot. Keep the UI and displayed data unchanged.

| Slot | Capture |
|---|---|
| `agent-builder` | Complete: demo agent instructions, selected model, current published version (v6) |
| `skills` | Complete: library and the artifact-pages procedure with instructions and templates |
| `context` | Complete: library and glossary content with linked mode for on-demand reading |
| `knowledge-bases` | Complete: personal and organization collections |
| `knowledge-collection` | Complete: vstorm collection with document name, processing status and chunk count |
| `mcp-connections` | Complete: connected server catalog including GitHub and Notion; no credentials shown |
| `artifacts` | Complete: library and the OSS Launch Planner from the demo |
| `activity` | Complete: filtered run history and agent version comparison; status, tokens, duration and recorded cost |
| `run-detail` | The demo execution, tool calls and recorded cost |
| `approval` | Complete: actual pending execute action and decision controls |
| `routines` | Complete: existing weekly schedule editor, Monday at 06:00 UTC, message in Preview |

Ten screenshot slots are complete; `run-detail` remains pending.

## Previous capture provenance

The following records describe earlier captures. The light-mode refresh below supersedes their
dimensions and sidebar states for the eleven replaced light images; dark alternates are unchanged.
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

The Routines capture shows configuration of an existing schedule, not a completed execution or result.
It contains the generic reconciliation procedure; no schedule was saved or run for the screenshot.

Previous UI screenshots, the old CSV demo and its poster/animation were removed from the repository.
The documentation and presentation use explicit placeholders until new captures are ready.
Earlier assets remain recoverable from Git history; do not reuse them for the refreshed interface.

## Placement and positioning

The README leads with the open-source agent layer for companies: shared agents, knowledge,
automation and control over deployment and models. Use AI agent harness and Claude Code-like
only where they explain the execution model or a concrete example. Do not label the product a platform
or imply live multiplayer sessions, absolute data isolation, model parity or guaranteed search rankings.

The main reading path shows the demo followed by a visible feature table. Results, the MCP catalog, company knowledge and Activity
use full-width screenshots, interleaved with compact text-and-image rows for configuration, skills
and context. Approvals and routines close the gallery as compact rows. Additional library and collection views and the pending run-detail
capture sit in a collapsed supplement. The Routines row shows the existing weekly schedule editor. Team access,
installation and deployment controls follow the gallery; terminology remains defined in the feature copy.
The layout takes inspiration from stablyai/orca, using AgenticOS copy and original product captures.

## Paths and video embedding

Use relative paths for repository images (`docs/assets/screens/...`) so the README can be reviewed
on a feature branch. Check the light screenshots and their full-resolution links on GitHub.

The README uses a linked GIF outside a video element so the preview does not depend on
GitHub's mobile video player. The MP4 is stored alongside it; the explicit still-image link remains.

## Activity and integration scale

The Activity light/dark pair was captured on 2026-10-02 at 1751 × 1000 with the sidebar
collapsed, filtered to Claude Code like and Owner. Version summaries and individual run records
are visible. These are observed demo records, not a performance benchmark. The captures do not
replace the pending run-detail view of tool calls. Both files use lossless WebP without UI edits.

The README headline “5,700+ integrations through MCP” refers to discoverable server entries.
At revision `d76c6d597`, `backend/app/core/catalog/mcp_registry.json` contains 5,703 entries;
`mcp_servers.json` separately contains 99 curated entries. Do not add the two counts as unique
services or imply that all entries are connected, tested or first-party integrations. The public
copy names server entries and the need to configure credentials and tool access beside the claim.

## Current light-mode screenshots

The README displays light screenshots in both GitHub themes. Eleven light screenshots were
recaptured on 2026-10-02 at 1600 × 1000 with the sidebar expanded; dialogs retain navigation behind
the modal. The artifact detail remains the original full-screen product view with its authored dark
design. Lossless WebP conversions were verified pixel-for-pixel. Dark captures remain prior alternates.
The latest builder is current with v6; skill detail shows Source. The MCP page displayed 5,805 catalog
entries; the public claim stays at 5,700+ and describes discoverable server entries.

The user-provided Notion/GitHub demo remains the primary video, visible above the feature gallery.
The experimental overview films were rejected and are not included in the repository.

The Routines light screenshot was captured on 2026-10-02 with expanded navigation behind the native
modal. It shows Monday at 06:00 UTC and the message in Preview; it is a lossless WebP conversion.

The MCP catalog now spans both columns of the feature table for legibility. Its current light asset
is `light/mcp-catalog.webp` (formerly `light/mcp-connections.webp`): All categories, Any state,
5,805 server entries and a mix of connected and available services. Historical dark paths are unchanged.

## Shortened demo and mobile preview

The original hosted demo was downloaded on 2026-10-02. Remove source 00:30–00:39 from both video
and audio, retaining 00:00–00:30 and 00:39–00:46.466667. The result is 37.466667 seconds.
Audio has 30 ms fades around the cut; existing music and effects are otherwise retained.

- `oss-launch-planner-demo.mp4`: 960 × 546, 20 fps, H.264/AAC, 1,024,008 bytes.
- `oss-launch-planner-preview.gif`: 640 × 364, 3 fps, 56 frames, 18.66 seconds, 925,508 bytes.
  It shows the shortened demo at 2× speed without sound, disclosed below the image in each language.
- Both files fit the repository's 1 MiB asset limit. The GIF links to the shortened MP4.
- Original-resolution edited master and downloaded source remain in the local
  `Desktop/agenticos-demo-short` production folder.
- Validated full MP4 decoding, duration, GIF frame timing and sampled frames around the cut.
  Full-speed listening and physical mobile-device playback were not verified.
