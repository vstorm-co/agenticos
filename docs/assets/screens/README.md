# Console screenshots — what each one shows

Captured 2026-09-01 from a running deployment. Every screen is here twice, once
per theme, under the same filename: `light/agents.png` and `dark/agents.png` are
the same page. 27 pairs, plus the chat recording at the top level.

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

Eight more screens, added 2026-09-01 and in `dark/` alone. Every other screen on
this page is a pair; these are not, so a light-theme reader gets a dark image
until the light eight are captured.

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

- **No agent detail / Builder.** The single most important screen in the
  product — Build, Toolbox, MCP servers, Limits, Availability, History — is not
  in the set. Six tabs, so six pairs if all of them are wanted.
- **No sign-in or onboarding.** Whatever a first-time visitor meets is
  undocumented here.

## Paths

The README references these with **relative** paths (`docs/assets/screens/...`),
not `raw.githubusercontent.com/.../main/...`: a raw URL resolves against `main`,
so every image on a feature branch is a 404 until the branch merges, which makes
the one place you want to check the layout the one place it cannot be checked.

Relative `src` on an `<img>` is rewritten by GitHub and works. Relative `srcset`
on a `<source>` inside `<picture>` is less certain — if GitHub does not rewrite
it, a dark-mode reader simply gets the light image, which is a degradation
rather than a break.

**A `<video>` with a relative `src` does not work at all**, and nesting an
`<img>` inside it does not save the situation: fallback content is shown when a
browser cannot handle the *element*, not when its source resolves to nothing. So
the README hero is the animated WebP, which autoplays and loops everywhere, with
the mp4 behind a link beside it. A real player needs a URL GitHub itself serves
— `raw.githubusercontent.com/.../main/...` once this is on `main`, or an
attachment URL from dragging the file into an issue comment once.

## How the split was made

By mean luminance, not by hand: dark screens measure 17–31 and light ones
139–245, and the gap is wide enough that even a page dimmed behind a modal
classifies correctly — those land at ~140 rather than near 245, which is what
made the four dialog pairs the only ones worth checking twice.
