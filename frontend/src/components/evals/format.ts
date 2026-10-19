/** How an eval run's numbers read: money, shares and durations, in the reader's locale. */

/** A dollar amount from the decimal string the API sends; `null` reads as a dash. */
export function usd(value: string | null, locale: string): string {
  if (value === null) return "—";
  const amount = Number(value);
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: Math.abs(amount) < 1 ? 4 : 2,
  }).format(amount);
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
