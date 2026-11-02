# Console screenshots and recordings

## The captures

`light/` and `dark/` hold one WebP per console screen, in both themes. The README
uses selected framed views and `docs/screens.md` shows the full gallery. `capture.mjs` writes
every one of them:

```bash
ORG="Northwind Labs" AGENT="Finance Analyst" CHAT="Attached is" \
  node docs/assets/screens/capture.mjs              # every screen, light and dark
node docs/assets/screens/capture.mjs chat agents     # just these
THEMES=light BASE_URL=http://localhost:3000 node docs/assets/screens/capture.mjs
```

It signs in to a running deployment as the seeded owner, opens each screen in its
manifest at 1600 × 1000 CSS pixels and device scale 2, and saves it at 1600 pixels
wide. `ORG`, `AGENT` and `CHAT` choose the organization, the agent the Builder
screens show and the conversation the chat screen opens (by the start of its
title). Ids are looked up, so the script works against any deployment. Whatever
that deployment holds is what the pictures show. The screen list is in
`SCREENS`, ordered the way `docs/screens.md` describes them.

The static set was refreshed on **2 November 2026** from the local
**Northwind Labs** demo, using frontend and backend **1.35.3** plus the local
fix that respects a cleared Architect avatar. The demo runs in an isolated copy
of the local database. Uploaded agent-avatar references were cleared in both
the original local database and this copy; human avatars were preserved.

The company, documents and figures are fictional. Historical conversations and
apps are retained as examples. The new 30-step sales workflow and the document
and support workflows are **illustrative drafts**; their MCP connections are
disabled placeholders. The six-node batch example was actually executed locally
over three fictional company names, without models or external tools.

`demos/` contains the self-contained sources of three seeded apps (Launch Room,
Company Brain and Trail Supply) and an interactive Visuals source-trace example.
Their controls were checked in the real app iframe, including narrow viewports.
The wiki does not execute retrieval; the store uses deterministic recommendations
and never places orders or represents a live agent widget. The Visuals transcript
is an explicitly labelled fixture, not a generated-model run; saving it as an app
used the actual Visuals publishing service.

`demos/revenue-operations.json`, `document-intelligence.json` and
`customer-support.json` are portable workflow exports from the demo. They contain
no provider credentials. Their unresolved MCP pins require explicit connection
setup before execution; importing the drafts does not configure those services.

The video and its posters below remain historical recordings. Static screenshot
refreshes do not make those recordings captures of the current UI.

The README shows the light captures in both GitHub themes; the docs site
switches between `light/` and `dark/` with the reader's theme.

The annotated figures in `../readme/` are drawn over captures of their own;
`../readme/capture.mjs` writes those.

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
960 × 546, 20 fps, H.264/AAC, 1,024,008 bytes. The recording file is unchanged; the
README no longer shows it, and the presentation tour still plays it.

## README film

- Recording: https://github.com/user-attachments/assets/9d2a7923-a52e-4ee6-ab6a-734692824d5a
- Upload reference: https://github.com/vstorm-co/agenticos/issues/168#issuecomment-6204502542
- 2:11, 1920 × 1080, synthetic narration; a product film cut from two console
  recordings of the demo deployment.
- Poster: `agenticos-intro-play.webp`, the film's end card at 127 s with a play
  label drawn over it. The README links the poster rather than embedding a
  `<video>`, because GitHub's mobile app does not render one inline.

Earlier validation covered full MP4 decoding, duration and sampled frames around the cut.
Full-speed listening and physical mobile-device playback were not verified.

## Presentation and claims

Lead with **Open-source, self-hosted AI agent platform for your company's AI teammates.**
Keep the README, docs and landing positioning consistent. Show the actual product:
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


## Trail Supply follow-up: store, kit planner and widget

The gallery now also includes Kit Studio. Chat and chat-hero use the prepared
Trail Supply conversation with a populated list of specialist chats; the old CSV
conversation is still in the demo database. The store App has photography, product
details, filters, delivery-inclusive recommendations and a local demo bag. The kit
planner is rendered in Visuals and saved as a separate App. These console messages
are prepared fixtures, not a recorded model generation of the HTML.

`store-widget.webp` captures a separate local website with the actual AgenticOS
widget and a completed model answer from a published, read-only agent. Its catalog
is seeded in the instructions, not fetched from a retailer. The Apps remain
self-contained; their sandbox was not weakened to load an external widget. See
the reproduction guide below for build/seed/serve commands and image/run
provenance. No real orders, payments, credentials or customer data are included.

To reproduce the prepared chat captures, select
`CHAT="Trail Supply — build" HERO_CHAT="Trail Supply — build"` with Northwind Labs.
Capturing the external widget is separate: a real response requires explicitly
sending a message to its configured model, so the normal capture loop never does it.


## Trail Supply reproduction guide

Fictional catalog and policies, real product UI. `store.html` and `kit.html` are
self-contained templates after building. Product photography is illustrative;
product names, prices, stock, specifications and policies are invented.

### Build and verify

From the repository root, with the frontend dependencies installed:

```bash
node docs/assets/screens/demos/trail-supply-store/build.mjs
node docs/assets/screens/demos/trail-supply-store/verify.mjs
```

The builder embeds the three local WebP files as data URLs. The resulting
`../trail-supply.html` and `../trail-supply-kit.html` need no network and work under
the Apps/Visuals sandbox. Verification checks delivery-inclusive budget boundaries,
cart consistency, dialog keyboard behavior and mobile layouts. It calls no model.

### Seed an isolated local demo

Use a backend environment pointed at a **demonstration database**, the Northwind
Labs seed organization and its actual owner. The selected organization must
already contain Visuals Lab, Finance Analyst, Architect, Support Desk, Chief of
Staff, Onboarding Buddy, Sales Researcher and Tech Lead. The model-profile UUID
must refer to an existing configured profile in that organization.

With the backend environment loaded, from the repository root:

```bash
PYTHONPATH=backend backend/.venv/bin/python docs/assets/screens/demos/trail-supply-store/seed.py \
  --org ORG_UUID --user OWNER_UUID --model-profile MODEL_PROFILE_UUID \
  --store-origin http://127.0.0.1:3110 --output /tmp/trail-supply-demo.json --confirm-demo
python3 docs/assets/screens/demos/trail-supply-store/serve.py --metadata /tmp/trail-supply-demo.json
```

The seed publishes two private Apps through the artifact and Visuals services,
creates nine prepared conversations and a private, published Trail Guide agent,
and configures a public widget restricted to the selected local store origin.
The widget agent has no capabilities or commerce tools, a two-dollar monthly
budget and a three-step limit. The script uses the owner's actual membership;
it does not manufacture administrator authority. Existing named fixture threads
are reused, and only matching prepared messages are updated. It does not delete
other conversations or change provider credentials. Inspect existing resources
before reusing these fixture names with customized content.

The generated metadata contains resource identifiers and the public embed
snippet, not provider credentials. Keep it local; do not commit session files.
Serving the page alone calls no model. Sending a message through the widget uses
the configured model and is a real billed run if that provider charges for it.
The store's product finder, bag and checkout remain local demonstrations.

### Evidence and scope

The console transcript and its draw record are explicitly prepared fixtures, not
an LLM generation trace. Their HTML is rendered by the actual Visuals renderer,
and the kit planner was saved through the actual Visuals publishing service.
The separate website loads the unmodified AgenticOS widget script and talks to
its public WebSocket endpoint. `recorded-run.json` identifies an observed,
completed widget run. This establishes a read-only answer from the fictional
catalog in the published instructions; it is not live retrieval, stock lookup,
order placement, payment processing or a conversion experiment.

The product finder and Kit Studio include delivery in the budget calculation.
For example, the pack is €129 but €135 delivered; the pack plus bottle is €157
with complimentary demo delivery. The bag and recommendation must agree.

`images.json` records the three Unsplash image URLs and license. A pictured
object's real-world brand does not endorse this fictional store; the photography does not establish the invented product specifications.
