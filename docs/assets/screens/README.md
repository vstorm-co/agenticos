# README media and capture inventory

## Current README captures

Captured from the authenticated AgenticOS test deployment on 2 October 2026, with the app
detail and library refreshed on 3 October 2026, using
Chromium through Playwright. Every current README screenshot is a native **3200 × 2000
PNG** from a **1600 × 1000 CSS-pixel viewport at device scale factor 2**. The application
uses its light theme and expanded navigation. The organization-selection reminder is dismissed.
The featured app is now Meridian, a light-theme sales dashboard with clearly labeled demo data.

The PNGs are lossless browser captures: no upscaling, recomposition, image-generation edits or text
replacement. All fourteen files are below the repository's 1 MiB per-file limit. Open the linked
images in the README to inspect them at full resolution. `readme-captures.json` records paths,
dimensions, byte sizes, hashes and capture states.

| File in `light/` | View and preparation |
|---|---|
| `agent-builder.png` | Claude Code like agent, published v6, Build tab, instructions in Source and model selection visible |
| `chat.png` | User-selected existing sales CSV conversation; regional revenue chart and analysis; conversation list collapsed |
| `sandboxes.png` | Existing container-service connections and runtime selections; vault values are not exposed |
| `agents.png` | Existing agent catalog with descriptions and version states |
| `skills.png` | Design, Engineering, Finance and Research selected; six matching skills |
| `context-detail.png` | Existing Glossary open in Preview, enabled, linked for on-demand reading |
| `knowledge-collection.png` | User-selected vstorm collection, completed document with parser and chunk count |
| `artifact-detail.png` | Meridian · Revenue overview v1; agent-generated light dashboard, H1 / All regions, private visibility |
| `artifacts.png` | Refreshed library including Meridian, with previews, versions and visibility |
| `dashboard.png` | Saved custom layout: blue Usage & cost section, compact summary, bars for run trends and wider outcomes widget |
| `activity.png` | Existing last-30-days run history, statuses, tokens and recorded costs |
| `groups.png` | New empty Engineering, Finance, Operations and Research groups, alongside the pre-existing test group |
| `members.png` | Organization scrolled to its members and assigned roles |
| `roles.png` | Existing permission matrix, including all six built-in roles |

The dashboard layout and four example groups were saved through the application UI at the
user's request. Group descriptions explain departmental uses; no members or resource grants
were added. The chat composer selects Claude Code like for the next message. No message was
sent, agent run started, agent specification published or access policy changed for the 2 October
capture batch. Dashboard and Activity figures are existing test-deployment records, not a benchmark.

Directory mappings were inspected but not configured. That empty view is described in README
text rather than added as another screenshot. It maps external directory groups to an organization
role and optional local group at sign-in; it is not a department directory.

Authentication state and temporary capture tooling stay outside the repository. No password,
session token or browser storage is part of the media bundle.

## Meridian app refresh — 3 October 2026 { #meridian-artifact-refresh-3-october-2026 }

At the user's request, the Claude Code like agent built and published a new private app,
`meridian-revenue-overview`, titled **Meridian · Revenue overview**, version 1. It replaces the
OSS Launch Planner screenshot in the app section; the separate integration recording is unchanged.

- Conversation: `6f32affd-1845-4610-ac46-cdedf63438c9`.
- App: `b2b4c685-8075-4011-b6d6-1266b69cc79f` in the user-selected Vstorm organization.
- Source: a supplied design brief requesting a light executive sales dashboard, deterministic
  illustrative data, three charts, four KPI cards and functioning period/region filters.
- Data: Meridian is fictional. Figures are generated demonstration data, not customer results or
  a claim about AgenticOS revenue, performance or adoption. The page labels them visibly.
- Implementation: a self-contained page using the deployment's bundled Chart.js. The agent
  reported calculation and DOM checks; its sandbox had no browser, so browser checks were performed
  separately against the published app.

Verified all 12 period/region combinations in Chromium: trend and product-mix totals agree with
corresponding regional totals, and Q1 + Q2 equals H1 for every region. Checked filter-driven KPI
changes, Reset, a visible chart tooltip and mobile layout without horizontal page overflow.
The final capture uses H1 / All regions at the same native PNG 2× settings as the other images.
No image editing was used. Existing apps and their sharing settings were not changed.

## Earlier captures

Earlier captures mixed original 3502 × 2000 screenshots, 1751 × 1000 captures and a later
1600 × 1000 refresh. Some browser-tool output was scaled JPEG before conversion to WebP;
lossless WebP encoding cannot restore detail lost in that source. The current PNG captures
replace the README references rather than enlarging those files.

Existing light/dark WebP assets remain historical media. The README uses the fourteen PNGs
above in both GitHub themes. Dark alternates and additional earlier views were not recaptured
in this revision. Documentation and presentation placeholders are outside this capture refresh.

## Recorded integration example

- Original recording: https://github.com/user-attachments/assets/529c8a90-501e-45c7-81d1-0f8de7829953
- Original upload reference: https://github.com/vstorm-co/agenticos/issues/168#issuecomment-5937226436
- Current shortened recording: https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512
- Current upload reference: https://github.com/vstorm-co/agenticos/issues/168#issuecomment-5942800375
- Static poster: `oss-launch-planner-poster.webp`, extracted at 24 seconds from the supplied edited demo.

The recording shows a Notion brief becoming the OSS Launch Planner after GitHub research,
then audience selection and sharing. It uses Vstorm projects as demonstration material; the
repository metrics are a dated snapshot, not a live feed or customer outcome study.

The shortened cut retains source 00:00–00:30 and 00:39–00:46.466667: 37.466667 seconds total.
Audio has 30 ms fades around the cut. The local `oss-launch-planner-demo.mp4` derivative is
960 × 546, 20 fps, H.264/AAC, 1,024,008 bytes. The README embeds the uploaded shortened
attachment with a `#t=1` start offset and keeps direct full-video and static-poster links. GitHub
strips the `poster` attribute; the offset shows a decoded frame after the opening transition
instead of a blank player. The recording file is unchanged. There is **no expandable GIF fallback**.
Historical GIF files are not displayed by the README.

Earlier validation covered full MP4 decoding, duration and sampled frames around the cut.
Full-speed listening and physical mobile-device playback were not verified. This screenshot
refresh does not alter or re-record the video.

## Presentation and claims

Keep **Sovereign Agentic AI Layer** verbatim in all README heroes. Lead with the actual product:
builder, a linked task overview, installation and the recorded example. Follow with concrete
work in chat, knowledge, apps, operations and organization access. Keep the glass integration
collage after that product tour. Main screenshots are linked at full width; supplementary views use expandable
sections. Do not add decorative browser frames that reduce the readable interface area.

The Claude Code/Codex comparison concerns file and command workflows, not feature parity.
Command execution requires a configured execution-capable sandbox. Groups add resource access
alongside roles and individual grants; they do not reduce the access a role already gives.
Enterprise login requires deployment configuration. Self-hosting does not make external models
or tools local.

Describe the MCP figure as **server listings**, not tested integrations or unique apps. At
revision `d76c6d597`, the registry snapshot contained 5,703 entries and the curated catalog
contained 99 entries; do not add these as distinct services. Each connection still needs its own
setup and access review. The selected integration graphic and logo sources live in
`../integrations/`; the README does not repeat their attribution inventory.
