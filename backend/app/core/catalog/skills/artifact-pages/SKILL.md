---
name: artifact-pages
description: How to build a page to publish with publish_artifact - the mandatory skeleton, the served library set, the house style and every kit class, icons instead of emoji, three templates (one for live data), and how to change a page later.
category: design
---

# Building a page to publish

A published page is read by somebody who was not in the conversation, often
weeks later, sometimes on a phone. Build for that reader: the answer first, the
detail under it, nothing they have to scroll past to learn whether it matters.
It should look like a screen of the product it was published from - quiet,
precise, graphite - not like a landing page.

**Start from a template** (below) rather than an empty file. Every page,
template or not, follows the skeleton and the structural rules - the publish
result warns about a page that does not.

## The skeleton - every page, in this order

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Weekly sales - 22 Sep 2026</title>
  <link rel="stylesheet" href="lib/agenticos-3.css">
  <script src="lib/chart-4.5.1.umd.min.js"></script>
  <script src="lib/lucide-1.46.0.min.js"></script>
  <script src="lib/agenticos-3.js"></script>
</head>
<body>
  <main class="ao-page">
    <header class="ao-header">
      <div>
        <div class="ao-eyebrow"><i data-lucide="chart-no-axes-column"></i>Sales</div>
        <h1>Weekly sales - 22 Sep 2026</h1>
        <p class="ao-subtitle">Revenue is up for the third week running.</p>
        <div class="ao-meta">
          <span><i data-lucide="calendar"></i>15-21 Sep 2026</span>
          <span><i data-lucide="database"></i>CRM export</span>
        </div>
      </div>
    </header>

    <section class="ao-section">...</section>

    <footer class="ao-footer">...</footer>
  </main>
  <script>/* your own script, last */</script>
</body>
</html>
```

- **`<!doctype html>` is the first line.** Without it the browser draws the page
  in quirks mode and tables come out in a different text size.
- **The viewport meta**, or a phone shows the page zoomed out.
- **`lang`** is the reader's language; numbers and dates follow it.
- **Load order:** the stylesheet, then the libraries the page uses (Chart.js
  only with a chart), then `lib/agenticos-3.js`, then your own script.
- **`main.ao-page`** holds everything (`ao-page ao-page-narrow` for something to
  read rather than scan).
- **The header is one block.** `header.ao-header` holds one `div` with, in order,
  the eyebrow, the `h1`, the subtitle and the meta line. Buttons or tabs for the
  whole page go in a second child, `div.ao-header-actions`. For an icon beside the
  title, wrap them:
  `<div class="ao-header-title"><span class="ao-header-icon"><i data-lucide="ticket"></i></span><h1>...</h1></div>`.
- **The subtitle is the answer** in one sentence. The meta line is short facts -
  period, source, "Live" - never a sentence.

## What the page can load

The page runs in an isolated frame with **no network**. It cannot fetch data,
call an API or load anything from a CDN. Data you only need once goes in the
page; records that should stay current arrive through `agenticos.onData` (see
"Live data" below).

The deployment serves a small set of files beside the page, by these relative
addresses:

| File | What it gives you |
|---|---|
| `lib/agenticos-3.css` | The product's look, light and dark, and every class below |
| `lib/agenticos-3.js` | `window.AO`: chart defaults, number formatting, icons, tabs, `AO.onData`, `AO.records` |
| `lib/lucide-1.46.0.min.js` | Lucide icons, as `window.lucide` |
| `lib/chart-4.5.1.umd.min.js` | Chart.js 4, as `window.Chart` |
| `lib/d3-7.9.0.min.js` | d3 7, as `window.d3`, for anything Chart.js cannot draw |

Anything else you need, inline it: your own script, your own styles, images as
`data:` URIs. Never paste a whole library in when the set has it.
`lib/agenticos-2.css`, `lib/agenticos-2.js` and `lib/agenticos-1.css` are still
served for pages published against them; build new pages on version 3, and load
the CSS and the JS of the same version.

## Structural rules

- **Only the kit's classes.** Use the classes in the table below, or inline
  styles and a `<style>` of your own for anything else. A class that is not in
  the table does nothing, however likely its name sounds.
- **A table** is `table.ao-table` inside `div.ao-table-wrap`, with the header row
  in `<thead>` and the rows in `<tbody>` - from script, `table.createTHead()` and
  `table.createTBody()`, never rows appended straight to the table. Inside a card,
  use `ao-card ao-card-flush` and put the wrap straight in it.
- **`ao-num` is for numbers and dates**: on the `th` and every `td` of that
  column, and nowhere else. A status column is text.
- **A state is a message, not a gap.** Before data, `div.ao-loading`; for no
  data or nothing found, `div.ao-empty`. Inside a table wrap they are padded.
- **Icons are `<i data-lucide="name"></i>`**, never emoji unless the person asked
  for emoji. An icon added by script later is drawn too; `AO.icons(element)`
  draws one at once.
- **Badges for a status word**: `span.ao-badge`, with a tone class only where the
  tone means something.
- **Charts** go in `div.ao-chart` (or `ao-chart-sm`, `ao-chart-lg`) around a
  `canvas`, created with `AO.chart("#id", () => config)`.

## The house style

- **No accent colour.** No indigo buttons, no blue links, no gradients. The
  primary is graphite. Green (`ao-up`, `ao-badge-success`) and red (`ao-down`,
  `ao-badge-danger`) mean better and worse, amber (`ao-badge-warning`) means
  attention - never decoration.
- **Flat surfaces.** `ao-card` has a hairline border and no shadow. Do not add
  shadows, coloured backgrounds or borders of your own.
- **Sentence case** everywhere: titles, headers, buttons, table headers. No
  capitals for emphasis and no letter-spaced labels.
- **Icons where they help a label be found** - a stat, a section title, a meta
  line - not on every line. Names are Lucide's (lucide.dev): `calendar`,
  `database`, `trending-up`, `users`, `wallet`, `git-fork`, `circle-dot`,
  `git-pull-request`, `download`, `eye`, `triangle-alert`, `circle-check`,
  `info`, `clock`, `file-text`, `ticket`, `list`.
- **Numbers**: never hand-format. `AO.format.number(36924)` writes it the way the
  page's language does, `AO.format.compact`, `AO.format.percent(0.411)`,
  `AO.format.currency(v, "EUR")`, `AO.format.date(iso)`, and
  `AO.format.delta(v, { percent: true })` for a signed change.
- **Charts**: the kit gives Chart.js the product's fonts, grid, tooltip and a
  graphite series palette, and follows light and dark. Do not set colours unless
  a series means something; when it does, read a token:
  `AO.color("--ao-series-3")`, `AO.color("--ao-danger")`.

An organization may have edited this skill to describe its own brand. If this
section names other colours or fonts, follow those.

## Every class

This is every class `lib/agenticos-3.css` defines.

| Class | For |
|---|---|
| `ao-page`, `ao-page-narrow` | The width: a dashboard, or something to read |
| `ao-header`, `ao-eyebrow`, `ao-subtitle`, `ao-meta` | The header: one block of small label, title, one-sentence answer, then facts with icons |
| `ao-header-title`, `ao-header-icon` | An icon in a box beside the title |
| `ao-header-actions` | Buttons or tabs for the whole page, to the right of the title block |
| `ao-section`, `ao-section-header`, `ao-section-title`, `ao-section-desc` | A titled part of the page |
| `ao-grid-2`, `ao-grid-3`, `ao-grid-4`, `ao-grid` | Rows of cards that stack on a phone |
| `ao-stack`, `ao-row`, `ao-spacer` | A column with gaps; a wrapping row; the gap that pushes the rest of a row right |
| `ao-card`, `ao-card-header`, `ao-card-title`, `ao-card-desc`, `ao-card-flush` | A surface; flush for a table or list that runs to its edges |
| `ao-stat`, `ao-stat-label`, `ao-stat-value`, `ao-stat-foot`, `ao-delta` | A number with its label, its change and what the change is against |
| `ao-up`, `ao-down` | Better and worse, on a delta or a word |
| `ao-kpi-label`, `ao-kpi-value` | Older names for `ao-stat-label` and `ao-stat-value` |
| `ao-table-wrap`, `ao-table`, `ao-num`, `ao-strong` | A table that scrolls sideways on a phone; a number column; the row's name |
| `ao-tabular` | Digits of equal width outside a table |
| `ao-caption` | A line above a list: how many there are, what it is filtered by |
| `ao-note` | A line under a list: that it is cut, or that a filter no longer applies |
| `ao-list`, `ao-list-item` | Records as rows of a list instead of a table |
| `ao-loading`, `ao-skeleton` | Before the data: a line with a spinner; a grey bar standing in for text |
| `ao-empty` | No data, or nothing found |
| `ao-live` | "Live": a dot saying the records are read when the page is opened |
| `ao-badge`, `ao-badge-success`, `ao-badge-warning`, `ao-badge-danger`, `ao-badge-info`, `ao-badge-outline` | A status word; `ao-badge-info` is neutral but stands out |
| `ao-callout`, `ao-callout-warning`, `ao-callout-danger`, `ao-callout-success` | The one thing to know, with an icon first |
| `ao-kv` | A `dl` of labels and values |
| `ao-progress` | A bar: `<div class="ao-progress"><span style="width: 62%"></span></div>` |
| `ao-icon`, `ao-icon-box` | An element sized like an icon; an icon in a small square |
| `ao-tabs`, `ao-tab` | A segmented control; `data-ao-tabs` wires it (below) |
| `ao-toolbar`, `ao-input`, `ao-select`, `ao-button`, `ao-button-primary` | Filters and controls above what they act on |
| `ao-chart`, `ao-chart-sm`, `ao-chart-lg` | A chart's box: 18rem, 12rem, 24rem high |
| `ao-legend`, `ao-swatch` | A legend of your own, when the chart's is not enough |
| `ao-footer` | Sources, method and when it was made, at the bottom |
| `ao-muted`, `ao-small`, `ao-mono`, `ao-truncate`, `ao-link` | Text helpers |

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

Three templates are files of this skill. Read the one that fits and replace its
data rather than starting from an empty page:

- `templates/dashboard.html` - numbers at a glance: a header, four stats with
  their change, a tabbed chart, a table, a footer.
- `templates/report.html` - something to read: the answer in a callout, key
  facts, sections, a table, next steps.
- `templates/live-table.html` - records from a table that stay current: a
  binding drawn with `AO.records`, with its loading, empty and unavailable states.

Keep static data in one `const data = {...}` at the top of the script, as numbers
rather than formatted strings, so the next refresh changes one place. Data you
bound to a table does not live there: it comes from `onData`.

## Rules for the content

**The title says what and when.** `Weekly sales - 22 Sep 2026`, not `Report`.
Under it, one sentence that answers the question - the thing a reader who stops
there should take away. Say where the numbers came from and when, in the meta
line.

**One page, one question.** A page that answers three questions is three pages.
Do not show the same number twice: a stat card and a table row with the same
figure is one of them too many.

**Say what a change is against.** `+37` means nothing; `+37 vs the day before`
does. A change that is bad when it rises (refunds, errors, cost) is red when it
rises. With no previous value, show no delta - not "no previous day".

**Write in the reader's language**, and set `lang` on `<html>` to it.

**Links to other sites work**, but the reader is asked before one opens. Link
your sources; do not rely on a link for the page to make sense.

**Reuse the name** every time you refresh the same page, so the link people
bookmarked shows the new version. `list_artifacts` shows the pages you have.

**Check it on a phone in your head**: the grids stack, tables scroll, nothing is
wider than the screen.

## Live data

When the page shows records from a Virtual Table, bind it to a query instead of
copying the records in: pass `bindings` to `publish_artifact` - a table, or a
saved view whose filters and sort are copied, plus the fields, filters, sort and
limit you need - then read them in the page. Everyone who opens the page reads
the same records, with its owner's access.
For a table of records, let the kit draw it:

```js
AO.records("#tickets", null, { text });          // a loading line until the data comes
agenticos.onData(function (data) {
  AO.records("#tickets", data.tickets, {
    columns: ["title", "status", "opened"],        // optional: field names, in order
    badges: { status: { Open: "warning", Closed: "success" } },
    text,                                          // the states' words, in the page's language
  });
});
```

`AO.records(target, binding, options)` empties `target` and draws the binding
there: a `thead` from the fields' labels and a `tbody` of the records, numbers
and dates formatted and right-aligned, a single or multiple choice as badges,
every value written as text. With no binding it draws `ao-loading`; an
`unavailable` binding and an empty one draw `ao-empty`; a cut list adds an
`ao-note`. `options.text` takes `loading`, `unavailable`, `empty`, `truncated`
(`{count}` is the number shown), `yes` and `no`;
`options.labels` renames a heading and `options.format` (`{field: (value,
record) => text}`) writes a column your way. `AO.onData` is the same call as
`agenticos.onData`.

Drawing something else - stats, a chart, cards - from the records:

- **`onData(render)` is the default.** It runs with the first data and again on
  every refresh, so draw from scratch each time. `agenticos.data` is a Promise
  of the first data only.
- **Draw a loading state first** (`ao-loading` or `ao-skeleton`), then the data.
- **Draw `unavailable`.** A binding whose `status` is `unavailable` serves this
  viewer nothing. Show `ao-empty` "No data", not an empty chart.
- **Show a cut list.** When `truncated` is true, say the list is cut and why:
  `limit` is `records` or `bytes`. `count` is how many records you got.
- **Never `innerHTML` with record text.** Use `textContent`; a record is
  whatever somebody typed.
- Each record is `{id, <field>: value}`. Each field in `fields` has its `label`,
  `type`, `options` and `state`.
- Binding names: lower-case letters, digits and `_`. Field names: words of
  letters, digits and `_` with single spaces, any case - `Status` and `Created At`
  work, read as `record["Created At"]`. Both at most 64 characters; at most 5
  bindings and 50 fields per binding.

Data you need once still goes inline.

**Binding data is a decision for the page's owner.** Everyone who can open the page
reads the records, whatever their own access to the table, so bind only what all of
them may see - and the check you cannot make is the owner's. The publish result lists
each query in words; read it, because it is what the owner agrees to. When its
`consent` is `pending`, tell the person the owner still has to confirm the data in the
console, and that everyone else sees `audience` until then. A binding whose reason is
`awaiting_consent` is not a bug in the page. To share the page, call `share_artifact`:
it only asks, and the owner answers in the console.

## Changing a page you published

Do not rebuild a page to change a word. Call `read_artifact` with its name,
then `publish_artifact` with the same name and `edits`: each edit replaces text
that appears exactly once, copied from what `read_artifact` returned. If the
page changed since you read it, you are told to read it again.

Rebuild from the data when the numbers change; edit when the page does.
