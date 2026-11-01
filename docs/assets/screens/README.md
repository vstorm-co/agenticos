# Console screenshots and recordings

## The captures

`light/` and `dark/` hold one WebP per console screen, in both themes. The README
shows eight of them and `docs/screens.md` shows them all. `capture.mjs` writes
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

The current set was captured on 14 October 2026 from a local deployment's
**Northwind Labs** organization: a fictional company selling a fictional product,
Ledgerly. Its knowledge bases, context files, agent instructions and the revenue
CSV are synthetic. The conversations, the published revenue dashboard and the
runs they recorded are real runs of those agents on Claude Sonnet 5.5. The
dashboard's history and the approvals waiting there are seeded test records, not
usage figures or benchmarks.

The evals and Improve captures (`datasets`, `dataset-*`, `eval-run`,
`agent-evals`, `improve-*`, `knowledge-gaps`, `ai-assistance`) come from a
second organization, **Demo**, captured on 28 October 2026 with
`ORG="Demo" AGENT="Refund desk" GAPS_AGENT="Refund desk (audit)"`. Its Refund
desk agent answers made-up refund and delivery questions for an Acme store; its
answers, grades, eval runs and Improve sessions are real runs on GPT-4.1 mini.

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
