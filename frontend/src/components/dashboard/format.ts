/** Small display formatters shared by the dashboard's widgets. */

/** A serialised-Decimal (or number) as dollars. Display only - never arithmetic. */
export function formatUsd(value: string | number | null | undefined): string {
  const amount = Number(value ?? 0);
  return `$${amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** Milliseconds as human latency: 850 ms below a second, seconds above. */
export function formatMs(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })} s`;
}

/** Percent change vs a previous value; null when there is nothing to compare. */
export function deltaPercent(current: number, previous: number): number | null {
  if (previous <= 0) return null;
  return Math.round(((current - previous) / previous) * 100);
}
