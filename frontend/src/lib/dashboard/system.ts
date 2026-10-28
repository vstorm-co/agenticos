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
 * Card chrome - the header and body spacing - belongs to `WidgetFrame`
 * and to nothing else. A widget body sets its own *inner* rhythm
 * and never its outer padding.
 *
 * ## Data ink — one accent, quieter
 *
 * | Job                            | Token                                    |
 * |--------------------------------|------------------------------------------|
 * | A data mark (bar, line, area)  | `--color-chart` (indigo)                 |
 * | The unfilled part of that bar  | `--color-track` (the same hue, near the surface) |
 * | An area wash                   | the mark at 22% at the line, fading to 0 |
 * | A gridline or axis             | one step off surface, solid hairline     |
 * | A quiet surface                | `bg-muted` - the one token               |
 * | State                          | `success` / `warning` / `destructive`, reserved, always labelled |
 *
 * In colour since 2026-10-13: the near-grey ink this replaced made a page of
 * eleven cards read as one grey block. The mark clears the 3:1 floor a mark
 * owes its surface in both themes; the track is deliberately under any floor -
 * it carries no value, only a bar's extent, and every list that draws one
 * prints the number beside it.
 *
 * Nominal categories - surfaces, models, agents - keep **one** hue for the
 * bar, and say which row is which with the row's own face: the agent's avatar,
 * the provider's or the service's logo. Colouring each bar differently would
 * spend the identity channel re-encoding what bar length already says.
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
 * The surface a widget is drawn on: the app's panel, at rest.
 *
 * The chat composer, every menu and every drawer take the same surface; the
 * dashboard was the one full page of flat white cards, which read as a
 * different product on the one screen that shows the most of them at once.
 * `.panel-card` in `globals.css` is the resting weight of it - the same card
 * colour, a quieter edge, and a shadow that lifts rather than throws.
 */
export const CARD_SURFACE = "panel-card";

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

/**
 * Recharts wants numbers, not classes: the area wash's strength at the line.
 *
 * It fades to nothing at the baseline, so it is a shadow the line casts rather
 * than a block under it - averaged over the area it is lighter than the flat
 * tenth it replaced, which on the dark theme read as a grey slab with a line on
 * top. The fade carries no value: the line is the data, the wash only says
 * which side of it is "under".
 */
export const AREA_FILL_OPACITY = 0.22;

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
