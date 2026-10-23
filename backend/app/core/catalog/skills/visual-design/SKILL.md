---
name: visual-design
description: How to answer with the draw tool - when to answer in text, a table or a chart instead, and how to draw the four interactive answers (explain, compare, make a tool, follow a trip on a map); which kind to pick, size and layout, light and dark, streaming order, follow-ups to the conversation, diagram craft, three.js, Mermaid, and fixing a drawing. Five templates.
category: design
---

# Drawing in the conversation

A visual sits in the conversation, between your words, and is read in a few
seconds at the width of a chat column, often on a phone. It answers one question
better than a paragraph would. If it needs a caption to be understood, it is not
finished.

## Choose the form of the answer first

Decide per request, not per conversation. Most answers are still text.

| The person wants | Answer with | Why |
|---|---|---|
| A fact, advice, writing, code, a decision | Text | Nothing to look at or play with |
| Exact values side by side | A Markdown table | Every number readable and copyable; the chat renders it |
| A trend, a ranking, a share of a whole | `create_chart`, when you have it | The console draws it natively, in its own style, and a chat app gets a picture |
| To **understand** how something works or moves | `draw` - an explainer with controls, or a 3D model | The person changes one thing and sees what follows |
| To **compare** options | A table first; a chart on a follow-up | "Now chart it" turns your table into a `create_chart` of the same numbers - no drawing needed |
| A **tool for the moment** - split a bill, size a loan, convert units | `draw` - a working calculator | Inputs, a result that recalculates, and a reset |
| To **follow a trip** or see where things are | `draw` - a map with numbered pins | Order and distance are spatial |

Do not turn every answer into a dashboard, and do not draw what a sentence says.
Text around a drawing is short: what it shows and what to try, never a
description of the drawing itself. One request can need two forms - a table and
then a calculator - in one answer.

**Be truthful in the drawing.** Label numbers you assumed as assumptions, inside
the drawing, not only in chat. Coordinates, prices and times you know from
memory are approximate: say so. A line between two map pins is not a route, a
distance or a travel time unless you looked one up. Never invent sources, live
data or a saved state.

## Make it look designed, not generated

A drawing is judged in the first second. Most generated ones fail the same way:
a title and a pill above a grid of identical rounded cards, each with an icon, a
shadow and a gradient, labels in tiny grey capitals. That reads as a template.
Aim for the opposite - a calm, exact piece that looks made for this one answer,
in the product's own neutral look.

**Composition**
- One subject, large. The scene, the map, the chart or the result takes most of
  the area; the controls are compact, under it or beside it.
- No title over the drawing: the line under it in the chat already names it. If
  the person needs context, one plain sentence, not a heading and a subtitle.
- Left-aligned, on one grid of 8 pixels. Group things by space - 8 inside a
  group, 16-24 between groups - not by drawing a box around each.
- Show each value once. A slider that shows its value needs no chip repeating
  it; a chart with direct labels needs no legend.

**Surfaces**
- Separate areas by a step in tone (`var(--ao-muted)`) and by space, never by
  a 1px border around everything. Lines belong to tables, inputs and charts.
- No card inside a card, and no row of identical cards. Three numbers are a row
  of figures with their labels under them, not three boxes.
- No shadows on anything at rest, no gradients, no glows, no glass or blur. One
  radius for areas (12px) and fully round buttons.

**Colour**
- Every colour from the theme - `var(--ao-fg)`, `var(--ao-muted-fg)`,
  `var(--ao-muted)`, `var(--ao-border)`, `var(--ao-primary)` - or your own
  variables switched under `prefers-color-scheme`. Never a hex for text: on the
  transparent background it disappears in the other theme.
- Neutral graphite, with one signal for the thing the drawing is about. Green
  and red only for better and worse. No violet, indigo or blue-to-purple, no
  rainbow of categories unless the categories need telling apart.

**Type**
- Three sizes do the work: one large (the result, 32-44px, weight 600, tight
  tracking), the text (14-15px) and the small print (12-13px). Labels at weight
  500 in the full ink, not thin grey text.
- Sentence case. No small capitals with wide letter-spacing, no eyebrow above a
  heading, no "01 / 02" numbering, no emoji, no monospace outside code.
- Figures in `font-variant-numeric: tabular-nums` so they line up and do not
  jump as they change.

**Controls**
- One primary action at most, in the ink fill (`ao-button-primary`); the rest
  quiet, in the muted fill. One height for every control, about 36px.
- Real `<button>`s and labelled inputs; a visible focus ring; sliders with
  `accent-color: currentColor`.

**Words inside the drawing**
- Plain and specific: what the number is, in what unit, under what assumption.
  No marketing ("high-impact", "seamless", "unlock"), no filler sentence that
  restates the title.

**Charts, scenes and maps**
- Charts: `AO.chart`, faint gridlines, labels on the bars or lines rather than a
  legend where they fit, no 3D charts, no pie with more than five slices.
- Scenes: a matte, neutral model on a soft ground, framed to fill about two
  thirds of the stage; colour only the parts a control moves; no axis helpers or
  grid floors unless the lesson is the axes.
- Maps: the map kit's look as it is - do not restyle the pins or the cards.

**Before you finish, read it once as a stranger** and fix any of these: a title
or a pill above the drawing; boxes inside boxes; a row of look-alike cards; a
shadow, gradient or glow; tiny capitals; a hex colour on text; a value shown
twice; centred content in a narrow column; a button row with more than one
primary; a sentence that says nothing.

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
- **HTML: design for 640 pixels wide and grow to the column's width.** The page is
  laid out at the width of the conversation's text and shown whole, shrunk if it
  is taller than about 900 pixels. Start at the left edge, where the text starts:
  no centred `max-width` wrapper and no outer margin. A page under one screen
  tall reads best.
- **Never size the page to the window** (`100vh`, `height: 100%` on `body`): the
  frame grows to fit the page, the page grows to fit the frame, and the bottom -
  usually the Reset button - is cut. Give a scene or a map a fixed height, about
  320-420 pixels, and lay the controls out under it.

## Light, dark and the background

The drawing sits on the conversation itself, with no box around it, so **leave
its page background transparent** (`html, body { background: transparent }`,
after `agenticos-2.css`) and do not frame the whole drawing in a bordered card.
A scene or a map draws its own area with a soft fill and rounded corners; a
diagram draws no background rectangle at all. A poster with its own background (a
cream sheet, a night sky) may keep it: it is a picture, not a page.

The person may be in either theme. Never leave text black on a transparent background.

In SVG, put the colours in a `<style>` with variables and switch them - and
draw no background rectangle:

```svg
<style>
  :root { --ink: #18181b; --muted: #71717a; --line: #d4d4d8; --box: #f4f4f5; }
  @media (prefers-color-scheme: dark) {
    :root { --ink: #fafafa; --muted: #a1a1aa; --line: #3f3f46; --box: #27272a; }
  }
  .box { fill: var(--box) }
  .label { fill: var(--ink); font: 600 15px system-ui, sans-serif }
</style>
```

In HTML, load `lib/agenticos-2.css` - it follows the theme - or use
`prefers-color-scheme` the same way.

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

In HTML: **all the styles first**, in one `<style>` in the `<head>`, then the
markup, then the scripts at the end. The person sees nothing until the styles
are closed, then the markup as you write it; scripts run once you finish. So do
not write half a page that depends on a script to look like anything - write the
static structure as markup and let the script fill in the values. Set `height`
to about the finished height, so the conversation does not jump while you write.

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

## Explain: controls that show cause and effect

The person should change one thing and see what follows: a slider for each
variable that matters, its value beside it, a Play that runs the interesting
case, and a Reset to where you started. Start on a state that already shows the
point. Name the moving parts the way the person would.

- Every control has a visible label and its current value; changing it updates
  the result at once (`input` events, not `change`).
- Put the result where the eye already is - next to the controls or right under.
- Use `lib/agenticos-2.css` for the controls and `AO.chart` for charts (it follows
  the theme). Keep the data in one object at the top of the script.
- Keyboard works: real `<button>`s and `<label>`led inputs, a visible focus.
  Respect `prefers-reduced-motion` and never autoplay forever.

Start from `templates/explainer.html` (sliders and a chart) or
`templates/scene.html` (a 3D aircraft with pitch, roll and yaw).

## Make a tool: a calculator that is right

- Real inputs with labels and units, defaults that already give an answer, and a
  Reset that restores both the inputs and the result.
- Check every input before computing - `valueAsNumber`, `Number.isFinite`, the
  domain's limits, a zero divisor - and show a sentence instead of `NaN`,
  `Infinity` or the last answer. `min` and `max` on an input do not stop typing.
- Keep full precision inside; format only the output (`AO.format`). Say the
  formula or the assumption that matters - "tip on the bill before rounding".
- Never `eval` what the person typed.

Start from `templates/calculator.html`.

## Compare: a table, then a chart

Write the comparison as a Markdown table with the criteria as rows or columns,
units in the header and a line under it on what you assumed. When the person
asks to see it ("chart it", "which is cheapest over five years"), call
`create_chart` with the same numbers - the table stays above, the chart answers
the follow-up. Draw a comparison only when the person needs to weigh it
themselves: sliders for the weights, the ranking recalculated.

## Follow a trip: a map

Load Leaflet and the map kit, then hand it the stops:

```html
<link rel="stylesheet" href="lib/leaflet-1.9.4/leaflet.css">
<script src="lib/leaflet-1.9.4/leaflet.js"></script>
<script src="lib/agenticos-map-2.js"></script>
<div id="trip"></div>
<script>
  AOMap.itinerary("#trip", {
    stops: [{ name: "Tokyo", lat: 35.68, lng: 139.77, day: "Days 1-2", note: "Asakusa, Shibuya" }],
    followUp: { label: "Plan this stop", text: (stop) => `Plan ${stop.day} in ${stop.name}.` },
    labels: { pause: "Pause", resume: "Resume", replay: "Replay" },
  });
</script>
```

It shows numbered pins joined in order by a dashed line, replays them dropping
one by one on request (`autoplay: true` plays them on load), and lays the stops
out as cards under the map; clicking a pin or a card
jumps to it. Your instructions say whether this deployment has map tiles: with
them it is a real map with its credit under it, without them an outline of the
stops. Without tiles, say so in your answer - not as a note inside the drawing -
with the reason your instructions give. Pass `labels` in the person's
language. A stop may carry `image` (`{{image:NAME}}` from `images`), `imageAlt`,
and the photo's `credit` and `creditUrl` - show the author and the licence for
every photo you did not make. Two to twelve stops read best.

The itinerary is a whole layout - map, controls and stop cards - 16:9 of the
page's width and never lower than its `height`. Put its element straight on the page: no border, background or
`min-height` around it, and no second list of the same stops beside it - the
cards are that list, and a framed box with a fixed height leaves the map touching
its edges over a band of empty space. Put any day-by-day detail in the stops'
`note`, or under the map.

Start from `templates/itinerary.html`.

## Continue the conversation from a drawing

A control in a drawing can hand the person's choice back to you:

```js
const ask = document.getElementById("ask");
const offer = () => { ask.hidden = !(window.agenticos && agenticos.canFollowUp()); };
offer();
addEventListener("agenticos:host", offer);
ask.addEventListener("click", () => agenticos.followUp(`Plan day 3 in Kyoto, budget ${budget} EUR`));
```

The console shows the text under the drawing and sends it only when the person
clicks Send, so write it as a message they would send: the values they chose
and the question, in their language, under 2,000 characters. Label the button
as the action ("Plan this stop", "Use these numbers"). Call it only from a
click - never on load, on a timer or while a slider moves. Hide the button while
`canFollowUp()` is false: outside the chat, in a saved app, nobody would receive
it. Sliders, filters and calculations stay local and send nothing.

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

- Size the renderer to its stage element, cap `setPixelRatio` at 2, and resize
  with a `ResizeObserver` on the stage.
- `OrbitControls` with `enableDamping` so the person can turn the scene; aim the
  camera at the subject and frame it fully on first render.
- A hemisphere light plus one directional light; `MeshStandardMaterial` with
  real colours. No textures from the network - build materials and shapes in
  code (`CapsuleGeometry`, `CylinderGeometry`, `TorusGeometry`, groups).
- Animate with `renderer.setAnimationLoop`, and stop moving when
  `matchMedia("(prefers-reduced-motion: reduce)")` matches.
- Model with groups so parts move together (a rotor on a hub on a body), and
  colour the part a control moves.

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
