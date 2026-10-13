---
name: artifact-pages
description: How to build a page to publish with publish_artifact - the served library set, the house style and its components, icons instead of emoji, two templates, and how to change a page later.
category: design
---

# Building a page to publish

A published page is read by somebody who was not in the conversation, often
weeks later, sometimes on a phone. Build for that reader: the answer first, the
detail under it, nothing they have to scroll past to learn whether it matters.
It should look like a screen of the product it was published from - quiet,
precise, graphite - not like a landing page.

## What the page can load

The page runs in an isolated frame with **no network**. It cannot fetch data,
call an API or load anything from a CDN. Put the data in the page.

The deployment serves a small set of files beside the page. Load them by these
relative addresses - they cost nothing to include and every page gets the same
version:

| File | What it gives you |
|---|---|
| `lib/agenticos-2.css` | The product's look, light and dark, and the `ao-` components below |
| `lib/agenticos-2.js` | `window.AO`: chart defaults, number formatting, icons, tabs |
| `lib/lucide-1.46.0.min.js` | Lucide icons, as `window.lucide` |
| `lib/chart-4.5.1.umd.min.js` | Chart.js 4, as `window.Chart` |
| `lib/d3-7.9.0.min.js` | d3 7, as `window.d3`, for anything Chart.js cannot draw |

Load the libraries first, the kit after them, your own script last:

```html
<link rel="stylesheet" href="lib/agenticos-2.css">
<script src="lib/chart-4.5.1.umd.min.js"></script>
<script src="lib/lucide-1.46.0.min.js"></script>
<script src="lib/agenticos-2.js"></script>
```

Anything else you need, inline it: your own script, your own styles, images as
`data:` URIs. Never paste a whole library in when the set has it.
(`lib/agenticos-1.css` is still served for pages published against it; use 2.)

## The house style

- **No accent colour.** No indigo buttons, no blue links, no gradients. The
  primary is graphite. Green (`.ao-up`, `.ao-badge-success`) and red (`.ao-down`,
  `.ao-badge-danger`) mean better and worse, amber (`.ao-badge-warning`) means
  attention - never decoration.
- **Flat surfaces.** `.ao-card` has a hairline border and no shadow. Do not add
  shadows, coloured backgrounds or borders of your own.
- **Sentence case** everywhere: titles, headers, buttons, table headers. No
  capitals for emphasis and no letter-spaced labels.
- **Icons, not emoji.** Write `<i data-lucide="star"></i>`; the kit turns it into
  the icon, sized to the text it sits in. Use one where it helps a label be
  found - a stat, a section title, a meta line - not on every line. Names are
  Lucide's (lucide.dev): `calendar`, `database`, `trending-up`, `users`,
  `wallet`, `git-fork`, `circle-dot`, `git-pull-request`, `download`, `eye`,
  `triangle-alert`, `circle-check`, `info`, `clock`, `file-text`. **Use emoji
  only when the person asked for them.**
- **Numbers**: never hand-format. `AO.format.number(36924)` writes it the way the
  page's language does (set `<html lang="pl">` for a Polish reader),
  `AO.format.compact`, `AO.format.percent(0.411)`, `AO.format.currency(v, "EUR")`,
  `AO.format.date(iso)`, and `AO.format.delta(v, { percent: true })` for a signed
  change. Numbers in tables are right-aligned: `class="ao-num"` on the `th` and
  every `td` of the column.
- **Charts**: the kit gives Chart.js the product's fonts, grid, tooltip and a
  graphite series palette, and follows light and dark. Create charts with
  `AO.chart("#id", () => config)` - the function lets it rebuild the chart when
  the reader switches theme. Do not set colours unless a series means something;
  when it does, read a token: `AO.color("--ao-series-3")`, `AO.color("--ao-danger")`.
  Put every canvas in `.ao-chart` (18rem), `.ao-chart-sm` or `.ao-chart-lg`.

An organization may have edited this skill to describe its own brand. If this
section names other colours or fonts, follow those.

## The components

| Class | For |
|---|---|
| `.ao-page`, `.ao-page-narrow` | The width: a dashboard, or something to read |
| `.ao-header`, `.ao-eyebrow`, `.ao-subtitle`, `.ao-meta` | Title block: a small label above, one sentence of answer under, then period and source with icons |
| `.ao-section`, `.ao-section-header`, `.ao-section-title`, `.ao-section-desc` | A titled part of the page |
| `.ao-grid-2`, `.ao-grid-3`, `.ao-grid-4`, `.ao-grid` | Rows of cards that stack on a phone |
| `.ao-card`, `.ao-card-header`, `.ao-card-title`, `.ao-card-desc`, `.ao-card-flush` | A surface; flush for a table or list that runs to its edges |
| `.ao-stat`, `.ao-stat-label`, `.ao-stat-value`, `.ao-stat-foot`, `.ao-delta` | A number with its label, its change and what the change is against |
| `.ao-table-wrap`, `.ao-table`, `.ao-num`, `.ao-strong` | A table that scrolls sideways on a phone instead of breaking |
| `.ao-tabs`, `.ao-tab` | A segmented control; `data-ao-tabs` wires it (below) |
| `.ao-badge` (+ `-success`, `-warning`, `-danger`, `-outline`) | A status word |
| `.ao-callout` (+ `-warning`, `-danger`, `-success`) | The one thing to know, with an icon first |
| `.ao-kv` | A `dl` of labels and values |
| `.ao-progress` | A bar: `<div class="ao-progress"><span style="width: 62%"></span></div>` |
| `.ao-legend`, `.ao-swatch` | A legend of your own, when the chart's is not enough |
| `.ao-button`, `.ao-button-primary` | A control on the page (filters, toggles) |
| `.ao-footer` | Sources, method and when it was made, at the bottom |
| `.ao-muted`, `.ao-small`, `.ao-mono`, `.ao-truncate`, `.ao-empty` | Text helpers |

Tabs switch panels without script of your own:

```html
<div data-ao-tabs-scope>
  <div class="ao-tabs" data-ao-tabs>
    <button class="ao-tab" data-ao-tab="30d" aria-selected="true">30 days</button>
    <button class="ao-tab" data-ao-tab="90d">90 days</button>
  </div>
  <div data-ao-panel="30d">...</div>
  <div data-ao-panel="90d" hidden>...</div>
</div>
```

## Start from a template

Two templates are files of this skill. Load the one that fits and replace its
data rather than starting from an empty page:

- `templates/dashboard.html` - numbers at a glance: a header, four stats with
  their change, a tabbed chart, a table, a footer.
- `templates/report.html` - something to read: the answer in a callout, key
  facts, sections, a table, next steps.

Keep the data in one `const data = {...}` at the top of the script, as numbers
rather than formatted strings, so the next refresh changes one place.

## Rules

**The title says what and when.** `Weekly sales - 22 Sep 2026`, not `Report`.
Under it, one sentence that answers the question - the thing a reader who stops
there should take away. Say where the numbers came from and when, in `.ao-meta`.

**One page, one question.** A page that answers three questions is three pages.
Do not show the same number twice: a stat card and a table row with the same
figure is one of them too many.

**Say what a change is against.** `+37` means nothing; `+37 vs the day before`
does. A change that is bad when it rises (refunds, errors, cost) is red when it
rises. With no previous value, show no delta - not "no previous day".

**Write in the reader's language**, and set `lang` on `<html>` to it, so numbers
and dates follow.

**Links to other sites work**, but the reader is asked before one opens. Link
your sources; do not rely on a link for the page to make sense.

**Reuse the name** every time you refresh the same page, so the link people
bookmarked shows the new version.

**Check it on a phone in your head**: the grids stack, tables scroll, nothing is
wider than the screen.

## Changing a page you published

Do not rebuild a page to change a word. Call `read_artifact` with its name,
then `publish_artifact` with the same name and `edits`: each edit replaces text
that appears exactly once, copied from what `read_artifact` returned. If the
page changed since you read it, you are told to read it again.

Rebuild from the data when the numbers change; edit when the page does.
