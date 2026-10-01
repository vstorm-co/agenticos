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
| `context` | Company context content and attachment settings |
| `knowledge-bases` | Named collections |
| `knowledge-collection` | Documents, processing status and preview or search result |
| `mcp-connections` | Notion/GitHub connections and tools; credentials hidden |
| `artifacts` | Library and the OSS Launch Planner from the demo |
| `run-detail` | The demo execution, tool calls and recorded cost |
| `approval` | An actual pending tool action and decision controls |
| `routines` | Schedule, actual completed scheduled run and result |

The `agent-builder` and `skills` slots are complete; eight screenshot slots remain pending.
The pair was supplied on 2026-10-01 at 110% browser zoom with the sidebar collapsed,
and stored as lossless WebP at the original 3502 × 2000 resolution.
Files: `light/agent-builder.webp` and `dark/agent-builder.webp`. The poster is a frame from the supplied video, not a new UI capture.
The Skills captures were supplied on 2026-10-01 and stored as lossless WebP at
3502 × 2000: `light/skills.webp`, `dark/skills.webp`, `light/skill-detail.webp`
and `dark/skill-detail.webp`. They show the library and the artifact-pages procedure in Preview.

Previous UI screenshots, the old CSV demo and its poster/animation were removed from the repository.
The documentation and presentation use explicit placeholders until new captures are ready.
Earlier assets remain recoverable from Git history; do not reuse them for the refreshed interface.

## Paths and video embedding

Use relative paths for repository images (`docs/assets/screens/...`) so the README can be reviewed
on a feature branch. Check light/dark picture rendering on GitHub when adding the new pairs.

Use the stable GitHub attachment URL for the video, not a local MP4 or a temporary signed redirect.
The current attachment is listed at the top. A ranged GET returned `206` with `video/mp4` on 2026-10-01.
GitHub's Markdown renderer retains the video and controls but may strip the poster attribute;
the README also offers explicit video and screenshot links.

An image nested inside a video does not replace a broken source in a browser that supports video.
Keep the independent screenshot link. Do not commit local video masters; GitHub hosts the uploaded video.
