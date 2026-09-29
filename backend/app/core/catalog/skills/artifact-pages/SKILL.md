---
name: artifact-pages
description: How to build a page to publish with publish_artifact - the served library set, the house style, two templates, and how to change a page later.
category: design
---

# Building a page to publish

A published page is read by somebody who was not in the conversation, often
weeks later, sometimes on a phone. Build for that reader: the answer first, the
detail under it, nothing they have to scroll past to learn whether it matters.

## What the page can load

The page runs in an isolated frame with **no network**. It cannot fetch data,
call an API or load anything from a CDN. Put the data in the page.

The deployment serves a small set of files beside the page. Load them by these
relative addresses - they cost nothing to include and every page gets the same
version:

| File | What it gives you |
|---|---|
| `lib/agenticos-1.css` | The product's look, light and dark, and the `ao-` classes below |
| `lib/chart-4.5.1.umd.min.js` | Chart.js 4, as `window.Chart` |
| `lib/d3-7.9.0.min.js` | d3 7, as `window.d3`, for anything Chart.js cannot draw |

```html
<link rel="stylesheet" href="lib/agenticos-1.css">
<script src="lib/chart-4.5.1.umd.min.js"></script>
```

Anything else you need, inline it: your own script, your own styles, images as
`data:` URIs. Never paste a whole library in when the set has it.

## The house style

`agenticos-1.css` gives the page the console's neutral graphite look. Keep to it:

- **No accent colour.** Green (`--ao-success`, `.ao-up`) and red (`--ao-danger`,
  `.ao-down`) mean something - better and worse. Do not use them for decoration.
- **Series colours** are `--ao-series-1` to `--ao-series-6`: graphite steps
  first, status colours last. Read them with
  `getComputedStyle(document.documentElement).getPropertyValue("--ao-series-1")`
  so a chart follows light and dark.
- **Layout**: `.ao-page` for the width, `.ao-grid` for a row of cards,
  `.ao-card` for a surface, `.ao-kpi-label` and `.ao-kpi-value` for a number,
  `.ao-table` for data, `.ao-chart` for a chart's box (a fixed height, so the
  chart does not grow forever), `.ao-badge` for a label, `.ao-subtitle` under
  the title.

An organization may have edited this skill to describe its own brand. If this
section names other colours or fonts, follow those.

## Start from a template

Two templates are files of this skill. Load the one that fits and replace its
data:

- `templates/dashboard.html` - numbers at a glance: KPI cards, one chart, one table.
- `templates/report.html` - something to read: a summary, sections, a table.

Keep the data in one `const data = {...}` at the top of the script, so the next
refresh changes one place.

## Rules

**The title says what and when.** `Weekly sales - 22 Sep 2026`, not `Report`.
Put the same date in the page, and say where the numbers came from.

**One page, one question.** A page that answers three questions is three pages.

**Links to other sites work**, but the reader is asked before one opens. Link
your sources; do not rely on a link for the page to make sense.

**Reuse the name** every time you refresh the same page, so the link people
bookmarked shows the new version.

## Changing a page you published

Do not rebuild a page to change a word. Call `read_artifact` with its name,
then `publish_artifact` with the same name and `edits`: each edit replaces text
that appears exactly once, copied from what `read_artifact` returned. If the
page changed since you read it, you are told to read it again.

Rebuild from the data when the numbers change; edit when the page does.
