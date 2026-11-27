import Decimal from "decimal.js";

/** How an eval run's numbers read: money, shares and durations, in the reader's locale. */

/**
 * The limit a new improvement session is offered: getting to its first stop, then
 * every attempt it may make, rounded up to a cent. The start is priced only to the
 * first stop, but the limit caps the whole session, so it has to leave room for the
 * steps after it. A search session's total already holds its first search; each
 * later attempt searches again with the same budget.
 */
export function sessionLimit(quote: {
  total_usd: string;
  per_round_usd: string;
  max_iterations: number;
  search_usd?: string;
}): string {
  const Money = Decimal.clone({ precision: 80, rounding: Decimal.ROUND_CEIL });
  const whole = new Money(quote.total_usd)
    .plus(new Money(quote.per_round_usd).mul(quote.max_iterations))
    .plus(new Money(quote.search_usd ?? 0).mul(quote.max_iterations - 1));
  return Money.max("0.01", whole.toDecimalPlaces(2)).toFixed();
}

/** What a person typed as a limit, as the plain decimal the API reads. */
export function limitValue(text: string): string {
  return text.replace(/\s/g, "").replace(",", ".");
}

/** A 0..1 share as a percentage; `null` (nothing decided) reads as a dash. */
export function percent(rate: number | null, locale: string): string {
  if (rate === null) return "—";
  return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 }).format(rate);
}

/** Milliseconds as seconds with one decimal, or a dash when nothing finished. */
export function seconds(ms: number | null, locale: string): string {
  if (ms === null) return "—";
  return new Intl.NumberFormat(locale, {
    style: "unit",
    unit: "second",
    unitDisplay: "narrow",
    maximumFractionDigits: 1,
  }).format(ms / 1000);
}
