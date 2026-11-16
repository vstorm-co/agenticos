# Maps and spatial scenes people can read

Use depth or geography to answer the person's question. For an open-ended playful request, choose a memorable composed scene and useful controls; do not settle for tiny identical spheres against a flat gray plane.

## Maps

Start from `templates/route-atlas.html`: locally bundled geography, an explicit illustrated itinerary, a visible place list and a deliberate ocean/land/accent palette. No tiles or token are needed. Keep locations and values as labelled demonstration data unless supplied or verified.

- Include a visible title, scope, units and source. Use color to distinguish no data from zero and selected places from surrounding land. The neutral console foreground is usually a poor choropleth palette: choose sequential color shades with enough contrast in the actual frame's light and dark themes.
- Match the projection and extent to the question. A whole-country US focus includes Alaska and distant islands; combined with European stops it can produce a surprising crop. For intercontinental travel start with the complete world, then provide an explicit regional view. A regional comparison should not cut off the selected countries or route endpoints.
- Show place names and exact values in a nearby list, not only hover tooltips or tiny pins. Keep text at a readable screen size, prevent overlapping labels and use clear endpoints and directional order.
- Connect stops with an illustrated great-circle line only when that is what it represents. It is not a road itinerary, measured distance or travel duration. Put this distinction beside the map.
- Report unmatched countries and unavailable map data. Never describe a blank or cropped frame as verified. Check the actual published drawing, including theme changes and phone width.
- Set responsive width and redraw on container resizing with a bounded observer. Preserve selected filters; don't reset the whole document. Keep the geography local: remote tile URLs only work when the operator explicitly enables them.

## Three dimensions

Start with the existing module-based `templates/scene.html`, then art-direct the subject. Keep three.js imports behind the documented local import map. Use module scope; unsupported bare imports and CDN dependencies do not work in this surface.

1. Establish scale with a floor, contact shadow or reference grid; aim the camera at the subject. The main object should fill a useful part of the viewport, with room for labels. Set near/far planes deliberately.
2. Build a hierarchy of forms, materials and light: a readable silhouette, a restrained accent for the moving part, soft hemisphere fill and a directional key. Use color management and tone mapping supported by the bundled three.js release. Avoid a black unlit object in a dark scene or chrome/glow on every surface.
3. Add structure that teaches: exploded components, a cutaway, a labelled force, a trajectory or one selected part. Keep text as accessible HTML/SVG outside WebGL when possible. Offer named camera views and reset; drag-only navigation is insufficient.
4. Each control must change a visible property and its numerical explanation. Distinguish a stylized illustration from a physically validated simulation. Include units, approximations and ranges where relevant.
5. Fit the camera after resize, bound pixel ratio and geometry counts, and dispose replaced geometries/materials. Pause continuous animation offscreen and respect reduced motion. A paused scene should remain a good still image.
6. Catch initialization failures and leave a useful labelled fallback. If WebGL is unavailable, say so; never claim the 3D scene rendered from a lint-only result. Inspect a real screenshot, orbit the camera, test reset and use the controls at phone and desktop widths.

For school, favor comprehensible shapes, annotation and a small experiment. For work, prioritize precise labels, comparisons and source/assumption disclosure. For play, use composition, color and procedural variation while retaining predictable controls and a reproducible seed.
