---
name: project-docs
description: Write or fix the documentation site — add a page, update one after a behaviour change, fix a dead link or a failing docs build, add a diagram or an icon, or wire a new page into the nav. Use whenever docs/ or mkdocs.yml is touched, and whenever a code change alters behaviour a page describes. make docs-build runs --strict, so a dead link fails CI.
---

# The docs site

```bash
make docs                       # serve on :8001 (DOCS_PORT=8002 if it is taken)
make docs-build                 # --strict; CI runs this, a dead link fails the build
```

`docs/` is both the published site and the repository's own engineering notes — **one
copy, on purpose**. A second copy of "how a capability works" written for outsiders is
a copy that disagrees with the one contributors read. So: do not write a page that
restates another page. `mkdocs.yml`'s nav decides what an outside reader meets first;
nothing is duplicated for them.

The same principle governs these skills. A skill routes to the doc and adds the
operational layer; it does not paraphrase the doc.

## Where to write when behaviour changes

The table in `CLAUDE.md` under `## Documentation` maps topic → page. Keep it current
when you add a page.

## Three things that silently render wrong

These have all shipped broken. Check the rendered page, not the Markdown.

**Mermaid needs the custom fence.** Without `custom_fences` on
`pymdownx.superfences`, a ```` ```mermaid ```` block goes to the syntax highlighter and
the reader gets the graph's source in a code box. Configured now — do not remove it.

Verifying is harder than it looks: Material renders into a **closed shadow root**, so
the `div.mermaid` in the DOM is empty and `querySelector('.mermaid svg')` finds
nothing. That is indistinguishable from a broken render. A screenshot is the only
honest check. Mermaid itself loads from `unpkg.com` at page-view time, so diagrams do
not render offline or behind a strict CSP.

**Icons need `pymdownx.emoji`.** Without the twemoji index, `:material-download:{ .lg
.middle }` reaches the page as that literal string — the home page's grid cards
rendered their own source for a while.

**`--strict` does not validate anchors.** A `#fragment` that matches no heading passes
the build. Check fragments by hand, or with a script over the headings.

## mkdocstrings

The API reference is generated from docstrings rather than written twice — this
codebase puts its reasoning in docstrings, so a hand-written reference would be a worse
copy of something already there.

The collector is **static**, and `app/services/`, `app/api/` and `app/worker/` have no
`__init__.py`, so it cannot traverse into them: `::: app.services.foo` **fails the
build**. Reference those from prose with a source link until those packages are made
explicit.

Because the reference is generated: when behaviour changes, fix the **docstring**. A
prose page that repeats it will drift.

## The seven tabs

`AgenticOS · Features · Learn · Reference · Resources · About · Release Notes` —
FastAPI's arrangement, organised by what the reader is *doing* rather than by what a
page is.

**Learn is a sequence**, not a bag: Get started → Build the agent → Put it in front of
people → Keep it under control → the recipes. A page added there belongs at a
position.

**Files stay flat in `docs/`.** The nav does the grouping. Those paths are named in
`CLAUDE.md`, in these skills, in `scripts/docs_drift.py` and in backend docstrings, so
moving a file to get a prettier URL invalidates all of them.

`release-notes.md` is `CHANGELOG.md`, substituted at build time by
`scripts/mkdocs_hooks.py`. That is a hook rather than a `snippets` include because
snippets expand *after* every hook, so nothing could reach the included text to
rewrite its `docs/`-prefixed links — and `--strict` fails on the `docs/docs/…` they
resolve to.

## Adding a page

1. Write it in `docs/` (or `docs/howto/`, `docs/reference/`).
2. Add it to `nav` in `mkdocs.yml`, **at the position it belongs at** — a page outside
   the nav is a build warning under `--strict`.
3. Cross-link it from the pages a reader arrives from, and from `CLAUDE.md`'s table.
4. `make docs-build` and check the anchors.

## Voice

The site was rewritten into one register. Match it, because a page in the old one
reads as a different product.

**Second person, present tense, stating the decision and the reason it was taken**,
without hedging — "A dead server is skipped, not raised, because Pydantic AI enters
every toolset when a run starts." Explain *why*, never restate *what*. Prefer a table
over a list of five parallel sentences.

Three conventions, and a new or edited page owes all three:

- **Sentence case headings.** Product names and acronyms keep their capitals — Docker
  Compose, Google Drive, PostgreSQL, MCP, CONFIG_SCHEMA. Title Case is what the
  template shipped and what 126 headings were swept out of.
- **No paragraph over ~115 words.** The site is at zero. A fact appended to a
  paragraph is a fact nobody finds: give it its own paragraph, a bullet, or an
  admonition. A fact a reader has to have seen *before* acting is an admonition —
  `!!! danger` for a footgun, `!!! warning` for a surprise, `!!! info` for the reason
  behind a design.
- **A recap at the end** of any page long enough to need one: at most five bullets,
  each the thing a reader should leave with. Not a summary of the page — the five
  things.

`scripts/check_docs_paragraphs.py` is that count, and `make lint` runs it.

## Icons

`app/core/catalog/icons/<name>.svg` is served by `GET /catalog/icons` and drawn for a
catalog entry or provider whose id matches and which no compiled-in icon set carries.
The file's own colours are **ignored** — it renders as a `currentColor` silhouette, so
the console's monochrome register holds by construction. See `icons/README.md`.
