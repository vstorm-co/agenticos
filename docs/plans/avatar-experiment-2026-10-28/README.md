# Console portraits — 28 October 2026

Scope: agent and entity portraits, without changing the application logo or the
operator's uploaded pictures. No library upgrades. The installed `blobatar` and
`@blobatar/react` are both 2.7.0.

## Experiment

Run from `frontend/`: `bun run scripts/avatar-experiment.ts`.
The script renders the installed library directly to SVG and rasterizes it with
Sharp (already installed with Next.js). It does not open or automate a browser.
[Comparison](comparison.png): eight stable handles, three policies, light and
dark host surfaces, each at 24, 36 and 56 pixels. The bottom row compares the two
starter-agent portraits. This is a rendering experiment, not a full UI capture.

1. **Library defaults:** retain all ten silhouettes and six tones. Capsules are
   very flat at 24 pixels; nub/cloud shapes add protrusions; ink is low-contrast
   against the dark console. Random eye lean adds visual noise to dense lists.
2. **Silhouette limits:** use supported `traits.shape` array overrides to select
   round, organic and boxy silhouettes. Improves shape consistency but leaves dark
   tones and large rotations; the supplier-invoice sample remains hard to read.
3. **Balanced portraits, selected:** the same three shapes, pastel/mid/bright
   tones, restrained organic radii, balanced body proportions, modest boxy tilt
   and near-upright eyes. Hue and remaining geometry still follow the stable seed;
   explicit color slots retain their hue. No hand-written replacement renderer.

The library exposes `traits`, `hue`, `tone`, `palette`, backgrounds, expressions,
size and animation. Trait values are positions from 0 to 1, not drawing units.
Array overrides narrow the seed's choices without removing deterministic identity.
The app policy lives in `frontend/src/lib/avatar-policy.ts`. The desktop mascot
uses it when wearing an agent/custom face; authored cast silhouettes stay intact.

Normal portraits animate on hover; thinking agents and the standalone desktop
mascot can animate continuously. Blobatar's reduced-motion CSS still applies.
Unframed agent portraits scale to 110%, down from 125%, to leave containment room.
Architect's custom mark loses its grid and uses a rounded blue body. Starter
AgenticOS loses the dark surrounding plate and uses a violet face. Regenerate
starter PNGs with `bun run scripts/gen-agent-portraits.ts`; the regression test
checks the assets against their recipes. Existing persisted images are uploads
and are not overwritten by deployment. In the local preview, exactly two files
matching the previous starter PNGs byte for byte were refreshed, with backups;
other pictures were preserved.

## Console hierarchy

The implementation changes shared headers and settings sections, rather than a
single page: explanatory copy moves into keyboard-accessible contextual help.
Live dashboard summaries and destructive-action warnings remain inline. The
shared list filter disclosure now works on desktop as well as phones. Agent cards keep status and access visible, moving secondary metadata into Details. Skills and
Context show identity and a short summary first, with previews, sharing, usage and
actions behind Details. Organization, builder and project navigation gains icons.
The account menu opens the existing desktop readiness dialog directly; the
floating setup counter is removed. Budget rows use the common agent avatar.

Focused component tests cover disclosure, permission-sensitive actions, keyboard
focus, setup reopening and avatar identity. Numeric layout checks sample 500
seeds. This work does not claim that every individual screen has been visually
reviewed; full application screenshots and native interaction checks were not run
because the user explicitly excluded Computer Use.
