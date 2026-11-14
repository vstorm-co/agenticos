/** How an eval run's numbers read: money, shares and durations, in the reader's locale. */

/**
 * A dollar amount from the decimal string the API sends; `null` reads as a dash.
 * An amount under a cent always shows four places, so two of them never read as
 * different precisions side by side.
 */
export function usd(value: string | null, locale: string): string {
  if (value === null) return "—";
  const amount = Number(value);
  const subCent = amount !== 0 && Math.abs(amount) < 0.01;
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: subCent ? 4 : 2,
    maximumFractionDigits: Math.abs(amount) < 1 ? 4 : 2,
  }).format(amount);
}

/**
 * An amount rounded up to whole cents. The product is trimmed first: 0.56 * 100 is
 * 56.00000000000001 in floating point, which would otherwise round up to 57 cents.
 */
function centsUp(amount: number): number {
  return Math.ceil(Number((amount * 100).toFixed(6))) / 100;
}

/**
 * A spending limit as a form field shows it: whole cents, rounded up so it never
 * shrinks, written the reader's way.
 */
export function limitText(value: string, locale: string): string {
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    useGrouping: false,
  }).format(centsUp(Number(value)));
}

/**
 * The limit a new improvement session is offered: getting to its first stop, then
 * every attempt it may make, rounded up to a cent. The start is priced only to the
 * first stop, but the limit caps the whole session, so it has to leave room for the
 * steps after it.
 */
export function sessionLimit(quote: {
  total_usd: string;
  per_round_usd: string;
  max_iterations: number;
}): string {
  const whole = Number(quote.total_usd) + quote.max_iterations * Number(quote.per_round_usd);
  return String(Math.max(0.01, centsUp(whole)));
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
