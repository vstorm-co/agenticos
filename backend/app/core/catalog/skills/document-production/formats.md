# File production contracts

## LaTeX paper

Read the supplied venue class and author instructions before choosing packages.
For an unconstrained draft, the bundled article template provides sane margins,
mathematics, figures, tables and hyperlinks. Replace its scaffolding with actual
content. Keep sections, data/figures and references in separate source files as
the document grows; name assets descriptively and use relative paths.

Probe the environment with `command -v latexmk`, `command -v tectonic`,
`command -v pdflatex`, `command -v biber`, `command -v bibtex`,
`command -v pdftoppm` and `command -v mutool`, as needed. A file-only workspace
cannot run those commands. Do not claim a compiler is installed because this
skill mentions one. Do not install a whole TeX distribution without considering
the available environment, time and the person's authorization.

When latexmk and the required engine exist, build from the document directory:

```sh
latexmk -pdf -interaction=nonstopmode -halt-on-error -file-line-error paper.tex
```

Use the engine required by the venue/language; a pdfLaTeX-only package choice
does not establish XeLaTeX compatibility. With an available standalone engine,
use its proper bibliography and repeated-pass sequence. Tectonic is an alternative
only where available and permitted; its missing bundle downloads are a dependency
failure, not a completed offline build. Do not enable shell escape for an unknown
document. Treat uploaded TeX, classes and build scripts as executable input.

Inspect the log for undefined references/citations, missing glyphs, unresolved
files, and overfull boxes. Fix the specific source problem; do not remove a figure
or citation just to silence the log. Check page count and extracted PDF text if
the available utilities support them. Render all pages, for example:

```sh
pdftoppm -png -r 120 paper.pdf review/page
```

Create the review directory first. Inspect the images with the available image
reader. A successful compile is not a visual review. Deliver `.tex`, `.bib`,
figure/data sources and PDF, plus the build command and any actual limitation.

## Editable presentations

Use an available, supported presentation generator such as `python-pptx` or
`pptxgenjs`; inspect its installed version and documentation before nontrivial
API usage. No particular library is guaranteed here. Choose the slide size
before positioning elements, then define margins, grid, fonts and a small set of
layouts. Match the supplied template when one exists. Keep text boxes, basic
shapes, tables and ordinary charts editable. Use vector figures where the target
supports them; verify fallback rendering instead of assuming it.

Outline each slide as claim, evidence, visual and speaker note. Source every
material number. Use sparse, readable text and direct chart labels; put supporting
detail in notes or an appendix. Avoid identical card grids on every slide.
Check long names, multilingual text, axis labels, footnotes and the last item in
lists. Notes add context and delivery cues rather than copying the slide text.

Save the generation script. Validate the generated ZIP/XML package and verify
that the expected slides, relationships and media exist. Render with an available
office/presentation renderer, inspect every slide thumbnail and full-size dense
slides, then repair and render again. A ZIP check cannot reveal overlap or a font
substitution. Browser HTML renamed to `.pptx` is never an acceptable export.

When rendering is unavailable, say which structural checks passed and which
visual checks remain. Offer the actual source file or an HTML deck when useful;
do not silently replace a requested editable deliverable.
