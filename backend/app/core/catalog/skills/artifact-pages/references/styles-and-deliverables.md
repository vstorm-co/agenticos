# Choose a visual language and a real deliverable

The audience and task choose the style. Respect a supplied brand. For an open brief, choose a direction deliberately instead of reusing one dashboard in every answer. A playful classroom activity and a board report can be equally polished without looking alike.

| Purpose                 | Composition and tone                                                                             | Useful visual choices                                                                                | Avoid                                                                                       |
| ----------------------- | ------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Learn a concept         | A concrete example, a manipulable model, an explanation of what changed, then a short self-check | Large readable labels, a small set of colors with stable meaning, annotated diagrams, optional hints | A wall of definitions; hiding the explanation behind a game score                           |
| Practice or play        | A clear challenge, immediate feedback and a reset; make rules and progress visible               | Expressive type, strong but accessible colors, original shapes, restrained celebratory motion        | Autoplay sound; flashing; random outcomes presented as facts; penalties without explanation |
| Read and decide at work | A claim supported by evidence, alternatives and their consequences                               | Editorial typography, whitespace, annotated charts, sources and dates near the claim                 | Repeated statistic cards with invented metrics; a decorative graph that says nothing        |
| Operate a workflow      | A task list or dataset, a selection/detail view and one clear primary action                     | Neutral interface, dense but legible tables, useful sorting/filtering, explicit status and failures  | Fake save/share buttons; assuming persistence or missing action bindings                    |
| Present a story         | One claim per slide, evidence, transitions that explain the argument, and a conclusion           | A deliberate grid, large type and meaningful figures; notes/appendix for detail                      | Shrinking paragraphs onto slides; a document chopped into equal rectangles                  |

## Starting palettes and type

These are starting points, not a required uniform. Define semantic tokens for background, text, secondary text, accent, border and feedback. Check the rendered contrast, including disabled controls, focus and chart annotations.

- An editorial report: warm paper, dark ink, a restrained green or rust accent; a system serif for headlines and a system sans for controls.
- A technical workbench: near-white or charcoal surfaces, a blue/teal accent, sans text and tabular numerals; monospace for actual code or identifiers.
- A classroom model: a calm light surface, dark text, a saturated blue and one warm comparison color; labels large enough to discuss on a projector.
- A playful activity: a warm or dark ground with high-contrast cyan, coral or yellow; oversized titles and original illustrations, with predictable controls.
- A visual story: an image-led opening when a real/admitted image helps, a strong reading path and fewer competing elements. Generate raster illustrations through the available image tool; keep labels and numerical data as text/SVG.

Use available system fonts or the runtime's local assets. A font name in CSS does not install that font. Keep a readable fallback and do not request remote fonts/CDNs. Light and dark versions need actual checking, not an automatic invert filter. Do not impose a new visual identity on the AgenticOS console itself.

## Formats are different contracts

- An interactive App is self-contained HTML published under a stable App name. Inline content, admitted libraries and supported bindings/actions are its execution contract.
- A browser presentation is HTML with slide navigation, keyboard access, a useful phone layout and a print layout that includes every slide. See `templates/slide-deck.html`. Navigation and print styles do not themselves produce a PDF file.
- A PDF is a fixed exported document. Use `export_artifact` for a published App when it is available, then inspect the actual pages. It requires an attached workspace and the configured isolated renderer, respects App access, refuses unavailable bound data, and limits a file to 50 pages and 20 MB. Verify page breaks, clipped content, fonts, charts and that all slides are present. Link the real file; never rename HTML to `.pdf`.

When an export tool or compiler is missing, identify the actual requirement and give a supported setup path. Do not show a working-looking export button with no implementation. Keep an HTML version useful while explaining the missing output precisely.

## Chat and channels

The chat can embed an interactive App or Visual; a messaging channel cannot execute its HTML. Publish a real App link for interactive work. For a requested static deliverable, use the supported file/image delivery tool for that same conversation and check the result. Export files from the actual final version. A room must not receive records the App preview deliberately withheld, and a public link needs the existing sharing/consent workflow. A link being posted does not grant anonymous access.
