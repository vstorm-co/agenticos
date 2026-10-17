---
name: visual-design
description: How to draw with the draw tool - which kind to pick, the size and layout the chat shows best, light and dark, writing in an order that streams well, diagram craft, interactive explainers, three.js scenes, Mermaid, and fixing a drawing. Three templates.
category: design
---

# Drawing in the conversation

A visual sits under your message and is read in a few seconds, at the width of
a chat column, often on a phone. It answers one question better than a paragraph
would. If it needs a caption to be understood, it is not finished.

## Pick the kind

| The person needs | Kind | Why |
|---|---|---|
| A diagram: architecture, a map, a comparison, an illustration, a poster | `svg` | Crisp at any size, grows on screen as you write it, scales to the panel by its `viewBox` |
| A flowchart, a sequence, an ER diagram, a state machine, a timeline, a gantt | `mermaid` | Ten lines instead of two hundred, and the layout is done for you |
| Something to play with: sliders, hover, tabs, a simulation, a game, a 3D scene | `html` | Script runs once the call is complete |

Prefer `mermaid` for anything that is boxes-and-arrows with more than six nodes:
hand-placed SVG gets crowded, Mermaid lays it out. Prefer `svg` when the layout
itself carries meaning (layers, regions, a timeline to scale) or the drawing
should look designed rather than generated.

## Size and layout

- **SVG: always a `viewBox`, no fixed `width`/`height`.** The panel fits the whole
  drawing by its `viewBox`, so the ratio is what you choose:
  - `0 0 960 540` (16:9) - architecture, flows, most diagrams;
  - `0 0 960 720` - denser diagrams;
  - `0 0 840 1188` (A-series portrait) - posters, one-pagers;
  - `0 0 1080 1080` - a square card.
- Text at **14 or more** viewBox units, titles 24-40, and nothing smaller than 12:
  the drawing is shown at about 650 pixels wide.
- Leave a margin of 32-48 units. Align to a grid of 8. Line things up - a diagram
  whose boxes are almost aligned looks broken.
- **HTML: design for 640 pixels wide and grow to more.** The page is laid out at
  the panel's width and shown whole, shrunk if it is taller than about 560 pixels.
  A page that is one screen tall reads best; for a scene, fill the frame
  (`html, body { height: 100% }`) and size the canvas to it.

## Light and dark

The person may be in either. Never leave text black on a transparent background.

In SVG, put the colours in a `<style>` with variables and switch them:

```svg
<style>
  :root { --bg: #ffffff; --ink: #18181b; --muted: #71717a; --line: #d4d4d8; --box: #f4f4f5; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #18181b; --ink: #fafafa; --muted: #a1a1aa; --line: #3f3f46; --box: #27272a; }
  }
  .bg { fill: var(--bg) } .box { fill: var(--box); stroke: var(--line) }
  .label { fill: var(--ink); font: 600 15px system-ui, sans-serif }
</style>
```

In HTML, load `lib/agenticos-2.css` - it follows the theme - or use
`prefers-color-scheme` the same way. A poster with its own background (a cream
sheet, a night sky) may keep it in both themes: it is a picture, not a page.

## Pictures

A drawing can use real pictures: a photo the person attached, an image in your
workspace, or - when you can read the web - a picture from an `https://` address.
List each in `images` with a short name and its source, and write
`{{image:NAME}}` wherever a URL goes:

```html
<img src="{{image:team}}" alt="The team at the offsite">
```

```svg
<image href="{{image:logo}}" x="40" y="40" width="160" height="80" preserveAspectRatio="xMidYMid meet"/>
```

```css
.hero { background: url({{image:cover}}) center / cover; }
```

- The source of an attachment is its file name, exactly as it was sent.
- Use a picture the way a designer would: crop it with `object-fit: cover` or
  `preserveAspectRatio="xMidYMid slice"`, round its corners, put text over it only
  with a scrim behind the text.
- Always write `alt` text.
- Up to six pictures, 2 MB each. Never paste an image as base64 into the drawing -
  that is what `images` is for.
- A revision keeps the pictures of the visual it changes; add new ones in its own
  `images`.

## Write it in the order it will be seen

The drawing appears while you write it, so the order is the animation:

1. `<style>` and `<defs>` (markers, gradients) first;
2. the background and the large regions;
3. the main shapes, in reading order - left to right, top to bottom;
4. connectors, then labels;
5. the legend and footnotes last.

In HTML: styles in the `<head>`, then the markup, then one `<script>` at the end.
Nothing runs until you finish, so do not write half a page that depends on a
script to look like anything - write the static structure as markup and let the
script fill in the values.

## Diagram craft

- **One idea per drawing.** Ten boxes at most before it becomes a map that needs
  its own explanation; group the rest.
- **Shapes mean something.** Rounded rectangles for services, cylinders for
  stores, a dashed outline for a boundary (a network, a team, a process). Keep one
  meaning per shape across the drawing.
- **Arrows**: define one marker in `<defs>` and reuse it. Straight or right-angled
  paths, never crossing a box. Label an arrow when the relation is not obvious
  (`writes`, `polls every 5 min`).
- **Colour is a signal.** Neutral by default, one accent for the thing the
  drawing is about, green and red only for good and bad. If colours encode
  categories, add a legend.
- **Fonts**: `system-ui, -apple-system, "Segoe UI", sans-serif` - there are no
  web fonts. Sentence case. Labels short enough to fit inside their box with
  room around them; measure by eye at 8-9 units per character at 15px.
- **Icons**: draw them from simple shapes, or use Lucide in HTML
  (`lib/lucide-1.46.0.min.js`, `<i data-lucide="database"></i>`). No emoji unless
  asked.

Start from `templates/architecture.svg`.

## Interactive explainers

- Every control has a visible label and its current value; changing it updates
  the result at once (`input` events, not `change`).
- Put the result where the eye already is - next to the controls or right under.
- Use `lib/agenticos-2.css` for the controls and cards and Chart.js through
  `AO.chart` for charts (it follows the theme). Keep the data in one object at
  the top of the script.
- Start from a state that already shows the point: the interesting case, not
  zeros.

Start from `templates/explainer.html`.

## 3D scenes

three.js is served as ES modules. The import map must come before your module:

```html
<script type="importmap">
  { "imports": { "three": "./lib/three-0.186.0/three.module.js",
                 "three/addons/": "./lib/three-0.186.0/addons/" } }
</script>
<script type="module">
  import * as THREE from "three";
  import { OrbitControls } from "three/addons/controls/OrbitControls.js";
</script>
```

- Size the renderer to the frame, cap `setPixelRatio` at 2, and resize on
  `resize`.
- `OrbitControls` with `enableDamping` so the person can turn the scene; aim the
  camera at the subject and frame it fully on first render.
- A hemisphere light plus one directional light; `MeshStandardMaterial` with
  real colours. No textures from the network - build materials and shapes in
  code (`CapsuleGeometry`, `CylinderGeometry`, `TorusGeometry`, groups).
- Animate with `renderer.setAnimationLoop`, and stop moving when
  `matchMedia("(prefers-reduced-motion: reduce)")` matches.
- Model with groups so parts move together (a rotor on a hub on a body).

Start from `templates/scene.html`.

## Mermaid

- `flowchart LR` for pipelines, `TD` for hierarchies; `sequenceDiagram` for who
  calls whom; `erDiagram` for tables; `stateDiagram-v2`, `gantt`, `timeline`,
  `mindmap` as named.
- Short node labels in quotes when they hold punctuation: `A["API (FastAPI)"]`.
- Group with `subgraph`. Leave the theme alone - it follows light and dark.
- A syntax error is reported back to you; fix the line it names.

## When the tool reports an error

`draw` and `revise_visual` tell you how the drawing rendered in the person's
browser. A script error, a library that did not load or a refused request
(`connect-src`, a CDN) is listed. Fix it with `revise_visual` in the same turn.
A request to the network cannot be fixed by retrying: put the data in the
drawing, or tell the person it needs a published app or an integration.

## Changing a drawing

For a correction, call `revise_visual` with the visual's id and exact
replacements, each copied from the source - not `draw` again. For a visual from
an earlier turn, read it first with `read_visual`. Draw again only when most of
it changes.

The person can save a drawing as an app from the panel. When they ask you to
put one on a page, publish it with `publish_artifact`: an `html` visual as it
is, an SVG inside a minimal HTML page.
