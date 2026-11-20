> t3OS adaptation: this reference adapts the pinned Anthropic source for accounting preparation and review. Examples are illustrative; source connector observations are checks to verify against the actual tool schema and current account, not product-wide capability claims. Follow the confirmed client/entity/period/currency/framework/jurisdiction and cite evidence. Read this file with `read_skill_resource` using its listed skill-root resource name; normalize relative links within this file to those registered names. This pack performs no external posting, payment, approval, filing, messaging, scheduling or page creation.

# Artifact style for accounting review

Use a clear ledger-like layout for a reusable report, review table or set of copyable drafts. A one-line answer does not need a separate page. Keep the key result in chat and the complete workpaper in the requested available format. Follow `document-format.md`; Notion/Canva requests produce transferable draft content for another workflow, not external pages. No fixed Claude Artifact runtime or publishing tool is assumed.

Use the engagement’s source cut-off, entity, period and ISO currency codes. Label the output prepared for review. Keep source rows and unknowns visible. All example businesses and figures below are illustrative; replace them with evidence from the actual engagement. Escape imported text, inspect local output and verify any copy control.

The source’s visual tokens and component examples follow. They can be overridden by supplied client brand preferences. Colors should still communicate review state, and text/number contrast must remain readable in light and dark themes.

```css
:root {
  /* House default palette — override with brand colors when known */
  --ink: #17211F;        /* primary text, warm near-black */
  --paper: #F4F3EE;      /* page background, cool stone, not cream */
  --paper-raised: #FFFFFF; /* card surfaces sitting on --paper */
  --line: #DEDCD1;       /* hairline borders and rules */
  --accent: #0B6B5C;     /* primary accent — confident ledger-teal */
  --accent-soft: #E4EFEC; /* accent tint for pill backgrounds, highlights */
  --amber: #B9781F;      /* secondary accent — "review this" signal */
  --amber-soft: #F6EBDA;

  /* Semantic — separate from the accent, never repurposed for branding */
  --good: #2E7D4F;
  --good-soft: #E4F0E8;
  --warn: #B9781F;
  --warn-soft: #F6EBDA;
  --critical: #B3392C;
  --critical-soft: #FBEAE7;

  /* Type — override the family names when the business has its own */
  --font-display: 'Zilla Slab', Georgia, 'Times New Roman', serif;
  --font-body: 'Public Sans', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-mono: 'IBM Plex Mono', 'SF Mono', Consolas, monospace;
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ink: #EDEAE2;
    --paper: #14201C;
    --paper-raised: #1B2A25;
    --line: #2C3A34;
    --accent: #4FBFA5;
    --accent-soft: #1E332C;
    --amber: #E0A559;
    --amber-soft: #362A16;
    --good: #6FCB94;
    --good-soft: #1D3226;
    --warn: #E0A559;
    --warn-soft: #362A16;
    --critical: #E37B6B;
    --critical-soft: #3A211C;
  }
}

:root[data-theme="dark"] {
  --ink: #EDEAE2;
  --paper: #14201C;
  --paper-raised: #1B2A25;
  --line: #2C3A34;
  --accent: #4FBFA5;
  --accent-soft: #1E332C;
  --amber: #E0A559;
  --amber-soft: #362A16;
  --good: #6FCB94;
  --good-soft: #1D3226;
  --warn: #E0A559;
  --warn-soft: #362A16;
  --critical: #E37B6B;
  --critical-soft: #3A211C;
}
```

Use system/local fonts when the runtime cannot load external fonts. Optional web fonts must comply with the actual runtime's network and content policy; no Artifact-specific host allowlist is assumed. Use supplied engagement brand tokens when available, and keep the house defaults otherwise. Branding is a presentation choice, not an instruction to browse a client website or update a shared profile.

---

## Type

- **Display** (`--font-display`) for page titles and section headers only.
  Weight 600, `text-wrap: balance`, never for body copy.
- **Body** (`--font-body`) for everything read as prose.
- **Mono** (`--font-mono`) for every number that sits in a column — currency,
  counts, dates in a table. Pair with `font-variant-numeric: tabular-nums`.

Keep a type scale and stay on it:

```css
--text-xs: 0.75rem;   --text-sm: 0.875rem;  --text-base: 1rem;
--text-lg: 1.125rem;  --text-xl: 1.375rem;  --text-2xl: 1.75rem;
--text-3xl: 2.25rem;  /* the one big number on a dashboard, sparingly */
```

---

## Layout — the ledger-card pattern

Content sits in bordered panels (`--paper-raised` on `--paper`, `1px solid
var(--line)`, `border-radius: 6px` — a slight, deliberate radius, not
`rounded-lg` everywhere by default). Panels stack with `gap`, not margin.
Wide tables get their own `overflow-x: auto` wrapper so the page never
scrolls sideways.

```css
.panel {
  background: var(--paper-raised);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 1.5rem;
}
.page {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  max-width: 840px;
  margin: 0 auto;
  padding: 2rem 1.5rem;
}
```

---

## Components

### Header

Every artifact opens the same way: confirmed business name (or a neutral report title if not yet known), the page's job in one line, and when it was generated. No hero,
no illustration.

```html
<header class="page-header">
  <div class="brand-mark">RM</div>
  <div>
    <h1>Cash Flow Snapshot</h1>
    <p class="meta">Ridgeline Mechanical · Generated Aug 21, 2026</p>
  </div>
</header>
```

`.brand-mark` is a two-letter monogram in `--accent-soft` background,
`--accent` text, `--font-display` — the same shape on every page, initials
drawn from the business name.

### Stat tile

The one number that matters, large, with a plain-English line under it, not
just a label.

```html
<div class="stat-tile">
  <div class="stat-figure">USD 18,240</div>
  <div class="stat-label">Cash on hand</div>
  <p class="stat-context">About 11 weeks of runway at current burn.</p>
</div>
```

`.stat-figure` uses `--font-mono`, `--text-3xl`, `tabular-nums`. The context
line is what makes it useful — a number alone is not an answer.

### Status pill

A small stamp-like tag, not a rounded pill-shaped badge — rectangular with a
slight radius, uppercase, letter-spaced. Semantic colors only.

```html
<span class="status status--good">On track</span>
<span class="status status--warn">Review</span>
<span class="status status--critical">Overdue</span>
```

```css
.status {
  display: inline-block;
  padding: 0.15rem 0.55rem;
  border-radius: 3px;
  font: 600 var(--text-xs) var(--font-body);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.status--good { background: var(--good-soft); color: var(--good); }
.status--warn { background: var(--warn-soft); color: var(--warn); }
.status--critical { background: var(--critical-soft); color: var(--critical); }
```

### Table

Hairline row dividers, no heavy grid. Numbers right-aligned in
`--font-mono`. Wrap in `.table-scroll` for width.

```html
<div class="table-scroll">
  <table>
    <thead><tr><th>Customer</th><th>Amount</th><th>Days overdue</th></tr></thead>
    <tbody>
      <tr><td>Corwin & Bay</td><td class="num">USD 1,240</td><td class="num">14</td></tr>
    </tbody>
  </table>
</div>
```

### Copy block

For text the owner is meant to paste elsewhere — an SEO fix, an email draft,
a job post. The button copies via the Clipboard API with a manual-select
fallback if the sandbox blocks it (test — do not assume it always works).

```html
<div class="copy-block">
  <button class="copy-btn" onclick="copyBlock(this)">Copy</button>
  <pre>Add this to your homepage title tag: "Ridgeline Mechanical — Same-Day HVAC Repair, Denver Metro"</pre>
</div>
<script>
function copyBlock(btn) {
  const text = btn.nextElementSibling.textContent;
  const done = () => { btn.textContent = 'Copied'; setTimeout(() => btn.textContent = 'Copy', 1500); };
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => fallbackSelect(btn));
  } else {
    fallbackSelect(btn);
  }
}
function fallbackSelect(btn) {
  const range = document.createRange();
  range.selectNodeContents(btn.nextElementSibling);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  btn.textContent = 'Selected — press Cmd/Ctrl+C';
}
</script>
```

### Checklist with progress

For a close process or an onboarding step list. Count derives from the
items, never hand-typed, so it can't drift out of sync.

```html
<div class="checklist">
  <p class="checklist-progress">3 of 9 done</p>
  <label><input type="checkbox" checked disabled> Bank feed reconciled</label>
  <label><input type="checkbox" disabled> Payroll posted</label>
</div>
```

### Footer

Every artifact ends the same way — quiet, small, `--text-xs`, `--line`
colored:

```html
<footer class="page-footer">Prepared for review — <strong>Cash Flow Snapshot</strong></footer>
```

---

## Both themes, always

Follow the token structure above exactly: bare `:root` for light, the
`prefers-color-scheme` media query guarded by `:not([data-theme="light"])`,
and `:root[data-theme="dark"]` repeating the same values so an explicit
toggle wins either direction. Every component reads colors from the tokens —
never a literal hex in a component rule — so a single override point (brand
colors, or the dark-mode block) recolors the whole page correctly.

---

## What not to do

- **Deliver one usable artifact in the supported local format.** Do not claim an external publication occurred. A downloadable HTML file is appropriate when that is the configured runtime’s output.
- **Do not invent a new palette per skill.** Every artifact uses these tokens.
  A one-off look defeats the entire point of a house style.
- **Do not add a hero, an illustration, or marketing copy.** These are
  operating tools, not pitches.
- **Do not skip dark mode.** Half the checklist above exists to prevent an
  unreadable page in the other theme.
- **Do not assume the clipboard API works.** The sandbox can block it —
  test, and ship the fallback.
- **Do not let this rule grow SKILL.md files.** A skill's delivery step is
  one line: "Render the result using the house artifact style
  (`./artifact-style.md`)," with the specific components named.
  All the CSS and component detail stays in this one file.

---

## Reference build

`reference/artifact-example.html` in this directory is a complete working
page using every component above, for copying structure from directly.
One caveat when copying: the example is a standalone file with a full
doctype/head/body skeleton so it opens in a browser. When a configured preview surface wraps content in its own document skeleton,
copy only the styles and the body content — never the doctype, html, head,
or body tags themselves.
