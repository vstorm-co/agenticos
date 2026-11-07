---
name: document-production
description: "Produce polished papers, LaTeX documents, editable presentation files and exported reports with reproducible sources, correct citations, build checks and visual review. Choose files versus HTML Apps honestly; verify available compilers and renderers."
category: design
---

# Deliver the format the person can use

Establish the reader, purpose, required format, source material, length and any
template or venue. Ask only unresolved consequential choices through
`ask_user_question`. Inspect supplied templates and existing documents first;
preserve their hierarchy, branding and meaningful content when editing.

| Deliverable | Route |
| --- | --- |
| Inline explanation or comparison | Text, chart or `draw`; load `visual-design` |
| Reusable report or interactive dashboard | `publish_artifact`; load `artifact-pages` |
| Browser presentation with keyboard navigation and print to PDF | `presentation-decks`, plus `deck-storyline` and `deck-review` |
| Editable `.pptx` | Workspace generation with an available presentation library; actual PPTX validation and rendering |
| Paper or substantial mathematical document | LaTeX source and bibliography, compiled PDF when a compiler exists |

Publishing HTML does not create a PowerPoint file or compile LaTeX. The isolated
visual/App frame cannot load arbitrary libraries, run TeX or fetch a CDN. Write
native document sources in the workspace and use its actual execution tools.
Read `formats.md` and the applicable template resource before producing files.
Check compilers, libraries and renderers before promising an export. Installing
dependencies or using another service follows the workspace's actual policy.

## Content before decoration

Outline the argument and evidence before laying it out. A paper distinguishes
question, prior evidence, method, results and limitations. A deck has a purpose
and one claim per slide; diagrams and charts support it rather than decorating
it. Label assumptions and synthetic data inside the output. Never invent research
results, citations, customer logos or an institutional affiliation.

Use a restrained type scale, consistent margins and a reading order appropriate
to the medium. For papers use the supplied venue template; otherwise begin with
`templates/paper.tex` and `templates/references.bib`. For HTML decks start from the
installed deck template. For editable slides keep text, tables and ordinary
charts native where feasible. A screenshot of a slide inside a PPTX is not an
editable presentation. Avoid shrinking text to hide overflow: split the content.

## Build, render, inspect, repair

1. Save editable sources, data and a reproducible generation/build command.
2. Build with the available compiler/library. Read warnings as well as exit code:
   missing citations, missing assets and overflowing boxes are visible defects.
3. Render every page/slide to images using an available renderer. Inspect a
   contact sheet for consistency and full-size pages for equations, dense tables
   and details. Review first, middle and last pages; review all slide thumbnails.
4. Fix clipping, overlap, bad contrast, broken symbols, tiny text, unsupported
   claims and placeholders. Rebuild and inspect the changed pages again.
5. Verify the final file exists, opens through the available reader and matches
   the requested format. Link both the final output and editable sources.

For Apps use `preview_artifact` when available; for inline visuals use their
read/revise/inspection tools. Interact with controls, test empty/unavailable data
and check a narrow viewport and both supported themes. Never call an unrendered
document visually reviewed. If execution or rendering is unavailable, provide
the source, exact pending build/check and a clear limitation instead of a fake
PDF/PPTX link. Keep iterating on observed defects rather than delivering the first
draft that merely compiles.
