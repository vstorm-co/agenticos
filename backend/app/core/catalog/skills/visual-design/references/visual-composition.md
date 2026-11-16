# Choose the visual relationship

A visual should make a specific relationship easier to inspect. Choose the medium before writing a large document.

| Need                                  | Good starting point                                             | What to verify                                                                   |
| ------------------------------------- | --------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Follow a process or architecture      | Mermaid or an SVG diagram with a clear reading direction        | Correct edges, labels and enough room at each node                               |
| Compare exact values                  | A table, aligned dot/bar plot or small multiples                | Units, common scale, zero baseline where bar length encodes value                |
| Explore an assumption                 | HTML with a small control panel beside a diagram/chart          | Visible formula, bounds, reset and changed result                                |
| Understand physical geometry          | A labelled 3D scene with sensible camera and a flat explanation | Depth matters; navigation works and failure has a readable fallback              |
| Follow places                         | The bundled country-outline map, pins and routes                | Coordinates and place labels; illustrative lines are not driving directions      |
| Create controllable graphic art       | SVG or Canvas with a reproducible seed                          | Composition, parameter range and a static/reduced-motion result                  |
| Create photographic/painterly imagery | The configured image-generation capability                      | Subject, crop, consistency and whether the result is an illustration or evidence |

## Compose deliberately

Lead with one thing the person should notice. Place the changed object and its explanation near the control that changes it. Use alignment, space and scale to establish a reading path; secondary annotations must remain legible. Distinguish a coordinate axis, an observation, a threshold and a selected state rather than styling them as equal decorations.

Use a coherent palette with a few semantic roles. Pair color with labels, line styles or shapes when it carries meaning. Typography can be quiet and precise for technical diagrams or more expressive for an editorial composition; it still needs comfortable line length and enough contrast.

## Encode data honestly

Label units and the source/period of observed data. Keep comparable quantities on comparable scales. Mark a non-zero axis and uncertainty when it matters. A simulation must disclose its model and input assumptions; animation does not validate that model. Avoid changing the axis to exaggerate a small difference.

Keep exact values available as labels or a compact table, including when a reader cannot hover. Missing is different from zero. A sampled or truncated dataset needs an explicit scope note. A 3D chart rarely helps a two-variable comparison.

## Art and imagery

For an original generative composition, choose the rule that creates the structure: repeated geometry, a field, growth, packing or another process suited to the brief. Store the seed and keep a useful range for density, spacing and variation. Avoid uncontrolled random changes every time a control moves.

For a raster asset, brief the subject, viewpoint, intended size and style constraints through the available image-generation capability. Use the tool's admitted image mechanism in the visual. Keep factual chart labels and precise typography as code-native text. Do not invent a photo source, copy an artist's work or present generated imagery as documentary evidence.

## Runtime-aware detail

Read the active drawing tool before selecting libraries or images. Its local d3, Chart.js, three.js and map kit can provide more than a generic card layout; load only what the relationship needs. The frame cannot retrieve a remote font, CDN or arbitrary API. For an unsupported feature, choose a working native HTML/SVG/Canvas treatment and explain the concrete limitation.
