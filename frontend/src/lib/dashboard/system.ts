/**
 * The dashboard's visual system: the rhythm a page is spaced on and the ink a
 * mark is drawn in.
 *
 * It exists because there was none. Across `components/dashboard` the spacing
 * classes in use were `p-0.5 p-1 p-2 p-3 p-4 p-5 p-6 p-8`, `gap-0.5`…`gap-5`
 * and eight `py-*` values - forty-one distinct numbers, none of them chosen
 * against the others. The rest of the product is no better, so "match the app"
 * was never an available fix: both were improvised, and a page of eleven cards
 * is where that shows.
 *
 * ## Rhythm — four values, and no fifth
 *
 * | Between                    | Value          |
 * |----------------------------|----------------|
 * | Elements inside a card     | `gap-3` (12px) |
 * | Card to card               | `gap-4` (16px) |
 * | A band's heading to its cards | `mt-3` (12px) |
 * | Band to band               | `space-y-10` (40px) |
 *
 * The one that was actually wrong is the last. Band-to-band was `space-y-6`
 * (24px) against card-to-card's 16px: three levels of structure inside eight
 * pixels of each other, which is why five bands read as one undifferentiated
 * mass. A band now sits four times further from its neighbour than a card does.
 *
 * Card chrome - the header's `px-5 py-3.5` and the body's `p-5` - belongs to
 * `WidgetFrame` and to nothing else. A widget body sets its own *inner* rhythm
 * and never its outer padding.
 *
 * ## Data ink — one accent, quieter
 *
 * | Job                            | Token                                    |
 * |--------------------------------|------------------------------------------|
 * | A data mark (bar, line, area)  | `--color-chart` (`brand-500`)            |
 * | The unfilled part of that bar  | `--color-track` (`brand-100` / `brand-900`) |
 * | An area wash                   | the mark at 10%, flat                    |
 * | A gridline or axis             | one step off surface, solid hairline     |
 * | A quiet surface                | `bg-muted` - the one token               |
 * | State                          | `success` / `warning` / `destructive`, reserved, always labelled |
 *
 * Measured, not judged: `brand-500` is 3.74:1 on the light card and 5.07:1 on
 * the dark one, both clear of the 3:1 floor a mark owes its surface, and both
 * quieter than the `brand-600` that shipped (4.99:1 light). The track is
 * deliberately under any floor - it carries no value, only a bar's extent, and
 * every list that draws one prints the number beside it.
 *
 * Nominal categories - surfaces, models, agents - keep **one** hue. That is the
 * rule, not an omission: colouring each bar differently spends the identity
 * channel re-encoding what bar length already says.
 *
 * The exception, and the only one: a chart whose segments are *parts of one
 * whole* - a ring, a stacked meter - where a segment's position says nothing
 * and colour is the only channel it has. Those take {@link seriesColor}.
 *
 * ## Figures
 *
 * A large standalone number is sans, semibold, with the font's own figures.
 * `tabular-nums` is for columns that align vertically - table rows and axis
 * ticks - and makes `121` look loose at display size anywhere else.
 */

/** Between two cards in a band's grid, and between a band's rows. */
export const CARD_GAP = "gap-4";

/** Between two bands. Four times the card gap, so a band reads as a band. */
export const BAND_GAP = "space-y-10";

/** From a band's heading down to its first row of cards. */
export const HEADING_GAP = "mt-3";

/** Between blocks inside one card - a figure and the chart under it. */
export const CARD_STACK = "gap-3";

/**
 * A filled data mark - a bar, a heatmap cell, the solid part of a meter.
 *
 * A step lighter than {@link STROKE_TOKEN} in light and a step deeper in dark,
 * because a fill covers area and a stroke is a hairline: the method's rule is
 * that saturated fills are for small marks, never large blocks. Every list that
 * draws one prints its value as text, which is the relief that lets the fill
 * sit under the 3:1 a lone mark would owe its surface.
 */
export const MARK_CLASS = "bg-chart-fill";

/** A stroked mark - a line, a sparkline. Thin, so it keeps the fuller tone. */
export const STROKE_TOKEN = "var(--color-chart)";

/** The unfilled part of a bar drawn in {@link MARK_CLASS}. */
export const TRACK_CLASS = "bg-track";

/** {@link TRACK_CLASS} as a colour, for the SVG and inline-style callers. */
export const TRACK_TOKEN = "var(--color-track)";

/**
 * The surface a widget is drawn on: the app's frosted pane, at rest.
 *
 * The chat composer, every menu and every drawer are glass; the dashboard was
 * the one full page of flat white cards, which read as a different product on
 * the one screen that shows the most of them at once. `.glass-card` in
 * `globals.css` is the resting weight of the same material - the card keeps its
 * own luminance, the ambient wash tints its corners as the page scrolls under
 * it.
 */
export const CARD_SURFACE = "glass-card";

/**
 * The categorical ramp, as CSS colours rather than classes - recharts renders
 * raw SVG and a Tailwind class cannot reach a `<Cell>`.
 *
 * Five, because past five a reader is matching swatches to a key rather than
 * reading a chart; a sixth category is "other". Defined in `globals.css`, where
 * the separation between them is measured.
 */
export const SERIES_TOKENS = [
  "var(--series-1)",
  "var(--series-2)",
  "var(--series-3)",
  "var(--series-4)",
  "var(--series-5)",
] as const;

/** The ramp's `index`th colour, wrapping - segment order decides the colour. */
export function seriesColor(index: number): string {
  return SERIES_TOKENS[index % SERIES_TOKENS.length] as string;
}

/**
 * The one quiet surface: a skeleton, an inset panel, a neutral meter track.
 *
 * `bg-foreground/5`, `bg-muted/20`, `bg-muted/30` and `bg-accent` were all
 * drawing this, sometimes two of them in one component.
 */
export const QUIET_SURFACE = "bg-muted";

/** Recharts wants numbers, not classes: the area wash, flat rather than a ramp. */
export const AREA_FILL_OPACITY = 0.1;

/** Recharts wants numbers, not classes: a line is 2px. */
export const LINE_WIDTH = 2;

/**
 * How tall a card's chart is, before its container gives it more.
 *
 * A chart has an aspect ratio whether or not anybody chose one. `min-h-28`
 * (112px) inside a full-width card gave the runs series a plot thirteen times
 * wider than tall, in which a real spike reads as a rounding error and a flat
 * fortnight reads as a rule.
 *
 * 128px, down from 192: a floor is only a floor if the card can hold it. An
 * arranged card's height is its owner's choice, and three grid rows leave 207px
 * for a body carrying a figure as well - so 192 overflowed, and what overflowed
 * was the x-axis, clipped at the card's edge. The chart is `flex-1` at every
 * call site, so a card with room still gives it everything above this.
 */
export const CHART_MIN_HEIGHT = "min-h-32";
