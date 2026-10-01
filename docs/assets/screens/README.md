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
| `agent-builder` | Demo agent instructions, selected tools and published version |
| `skills` | Library and a readable procedure |
| `context` | Company context content and attachment settings |
| `knowledge-bases` | Named collections |
| `knowledge-collection` | Documents, processing status and preview or search result |
| `mcp-connections` | Notion/GitHub connections and tools; credentials hidden |
| `artifacts` | Library and the OSS Launch Planner from the demo |
| `run-detail` | The demo execution, tool calls and recorded cost |
| `approval` | An actual pending tool action and decision controls |
| `routines` | Schedule, actual completed scheduled run and result |

All ten screenshots are pending. The poster is a frame from the supplied video, not a new UI capture.
The older assets below remain available for the existing documentation gallery.

## Previous console screenshots


Captured 2026-09-01 from a running deployment: 27 light/dark pairs, eight dark-only
Builder views and the previous chat recording. Matching filenames such as `light/agents.webp`
and `dark/agents.webp` show the same page in different themes.

Not a site page — this file is in `exclude_docs`, so `--strict` does not ask for
it in the nav.

## The pairs

| File | What it shows |
|---|---|
| `dashboard.webp` | The arrangeable dashboard: deployment-wide counters, service health, top organizations, answer quality |
| `agents.webp` | The agent catalog. Cards with draft/published state, owner and last edit |
| `agents-templates-dialog.webp` | The template gallery over the catalog — agents by industry; installing one creates a draft |
| `skills.webp` | The skill library — know-how written once and shared by every agent bound to it |
| `skills-gallery-dialog.webp` | The skill gallery over it; installing copies a skill into the organization |
| `skill-detail.webp` | One skill open for editing, with its category and the name the model refers to |
| `context.webp` | Standing context files — a glossary, a policy, a brand voice |
| `activity-runs.webp` | Activity → Runs. 262 runs over the last 30 days |
| `activity-run-detail.webp` | Activity → Runs with a run open: tokens, cost, duration, the timeline of turns and tool calls |
| `activity-approvals.webp` | Activity → Approvals — what is waiting on a person |
| `activity-spend.webp` | Activity → Spend, `$22.08` on the tab |
| `routines.webp` | Routines — what agents do on their own, on a schedule or on an event |
| `routines-event-trigger-dialog.webp` | The new-event-trigger dialog over Routines |
| `knowledge-bases.webp` | Collections list |
| `knowledge-base-detail.webp` | The `company` collection open, with its documents |
| `knowledge-base-upload-parsing-dialog.webp` | "Parse the next upload differently" — the per-upload parser override over the collection |
| `organizations.webp` | Organization switcher and members |
| `vault.webp` | Every key the organization has stored — replaceable, never readable again |
| `mcp-servers.webp` | MCP connections, organization-wide and personal |
| `channels.webp` | The chat platforms the organization is reachable on |
| `sandboxes.webp` | Sandbox connections — where agents run shell commands and keep files |
| `workspaces.webp` | The files agents are keeping, per conversation |
| `admin-users.webp` | Workspace administration → Users |
| `admin-organizations.webp` | Workspace administration → All organizations |
| `admin-system.webp` | Workspace administration → System health |
| `admin-deployment.webp` | Workspace administration → Deployment settings |
| `chat-sandbox-commands.webp` | Chat, mid-run: the agent thinking, then the shell commands it ran in the sandbox |

## The Builder — dark only

Eight more screens, added 2026-09-01 and in `dark/` alone. The 27 older console views listed above are pairs;
these eight have no light variant. They remain in the documentation gallery.

| File | What it shows |
|---|---|
| `builder-build.webp` | Instructions, model, endpoint - and `Draft differs from v40` beside `published` |
| `builder-toolbox.webp` | Capabilities as switches, with the per-tool approval gate |
| `builder-mcp-servers.webp` | Which connections and which of their tools this agent may reach |
| `builder-limits.webp` | The monthly cap and the step ceiling |
| `builder-availability.webp` | Where it answers, and which bots it is bound to |
| `builder-routines.webp` | Schedules and event triggers on the same tab |
| `builder-history.webp` | Every version it has had |
| `builder-visual-map.webp` | The agent as a graph; a dashed box is an unattached thing |

`chat-live-demo.mp4` — the chat recording, 20 s, 1280 wide, no audio, 968 KB,
with `chat-live-demo-poster.webp` and an animated `chat-live-demo.webp` beside it
for readers whose renderer will not play a video. The 8.9 MB 1912-wide master it
was made from is deliberately **not** committed; regenerate a derivative with:

```bash
ffmpeg -i <master>.mp4 -an -vf scale=1280:-2 -c:v libx264 -crf 27 \
  -preset slow -pix_fmt yuv420p -movflags +faststart chat-live-demo.mp4
```

## Two gaps worth filling

- **Light-theme Builder captures are missing.** The eight views above exist only in dark mode.
  Capture the selected current Builder view in both themes for the README refresh.
- **No sign-in or onboarding.** Whatever a first-time visitor meets is
  undocumented here.

## Paths and video embedding

Use relative paths for repository images (`docs/assets/screens/...`) so the README can be reviewed
on a feature branch. Check light/dark picture rendering on GitHub when adding the new pairs.

Use the stable GitHub attachment URL for the video, not a local MP4 or a temporary signed redirect.
The current attachment is listed at the top. A ranged GET returned `206` with `video/mp4` on 2026-10-01.
GitHub's Markdown renderer retains the video and controls but may strip the poster attribute;
the README also offers explicit video and screenshot links.

An image nested inside a video is fallback for renderers that support that fallback behavior. It does
not replace a broken video source in a browser that supports video. Keep the independent screenshot link.

The previous README used this attachment for the older CSV demonstration:

    https://github.com/user-attachments/assets/9a8e0f44-781c-4f93-990d-b5b7094cc8fc

Its `chat-live-demo.webp` and poster remain historical assets. The current README uses the OSS Launch
Planner video and poster instead. Do not commit local video masters; GitHub hosts the uploaded video.

## How the split was made

By mean luminance, not by hand: dark screens measure 17–31 and light ones
139–245, and the gap is wide enough that even a page dimmed behind a modal
classifies correctly — those land at ~140 rather than near 245, which is what
made the four dialog pairs the only ones worth checking twice.
