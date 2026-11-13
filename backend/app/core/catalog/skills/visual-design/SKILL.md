---
name: visual-design
description: "Explain, compare or explore through clear diagrams, interactive models, charts, maps and original graphics. Use for meaningful controls, spatial composition and visual verification; use Apps for a reusable published tool or report."
category: design
---

# Make a relationship visible

Start with what the person should understand or discover. A precise comparison may be a table or chart; a process may be a diagram; a changing relationship may need a control and an explanatory model. Use 3D when depth, viewpoint or physical structure carries meaning. A decorative animation is not evidence. Choose raster imagery for photographic or painterly subjects through the available image-generation tool; use SVG/Canvas for controllable geometry and exact labels.

Build around the subject rather than one repeated dashboard layout. Establish a reading path, one main visual relationship and a clear contrast between primary and secondary information. Use supplied branding when present. Keep typography readable, labels near their objects and color consistent in meaning. A diagram needs correct connections before ornament; a chart needs honest scales, units and sources before effects.

For exploration, provide a useful initial state, a small set of labelled controls and visible consequences. Show the assumption or formula driving a simulated result. Make reset predictable and support keyboard input. For procedural art, retain a reproducible seed; distinguish a visual pattern from measured data. Motion should explain change, provide pause when it continues and respect reduced motion.

Current tool contracts define the accepted format, image admission, library paths and available helpers. The Visuals frame has no arbitrary network: use admitted images and locally served assets, not remote fonts, a CDN or a guessed fetch endpoint. Keep Apps and Visuals helper versions separate. Edit a small region of an existing visual when that suffices instead of retransmitting the whole document.

Read the relevant reference or example only:

- `references/audience-and-style.md`: varied styles for school, play and work, with honest static/interactive delivery across chat and channels.
- `references/visual-composition.md`: medium selection, chart/diagram encoding, composition and asset guidance.
- `references/interaction-and-verification.md`: parameter design, accessibility, deterministic behavior and rendered checks.
- `references/maps-and-3d.md`: composed spatial scenes, readable geography, camera/lighting, themes and real render checks.
- `templates/route-atlas.html`: a local, responsive route map with a visible stop list and purposeful palette.
- `references/design-recipes.md`: existing chart, map, 3D and explainer helpers.
- `templates/comparison-lab.html`: a transparent scenario comparison with controls, units and an explanatory chart.
- `templates/generative-field.html`: seeded original Canvas art with meaningful parameters, pause and reset.
- `templates/explainer.html`, `templates/calculator.html`, `templates/scene.html`, `templates/architecture.svg`: established starting points.

For maps, use the bundled d3, topojson, world-atlas and `AOWorldMap.draw` country-outline kit by default, including pins and city-to-city itineraries. Use Leaflet and `AOMap.itinerary` only when the operator has enabled map tiles and street detail matters. Keep a country-outline fallback. A line between stops is not a road route; do not invent travel times or distances.

Render through the real drawing surface and try the interaction at phone and desktop widths. Verify geometry, legibility, focus, reset, limits and error states. A local HTML screenshot alone does not verify publication or data access. Share the actual result, its assumptions and any remaining limitation.
