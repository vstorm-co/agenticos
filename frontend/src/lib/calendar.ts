/**
 * Month-grid arithmetic for date pickers - pure, UTC, and component-free.
 *
 * The math lives here rather than inside a picker component so every future
 * calendar (the dashboard's range filter today, whatever needs one next)
 * renders the same grid: 42 cells, Monday-first, out-of-month days included
 * so the shape never jumps between months. Dates travel as ISO strings,
 * which compare correctly with `<`/`>` and never touch the local timezone.
 */

export interface CalendarCell {
  /** ISO date. */
  date: string;
  /** False for the leading/trailing days that pad the 6x7 grid. */
  inMonth: boolean;
}

export interface YearMonth {
  year: number;
  /** 1-12, as a human writes it. */
  month: number;
}

function toIsoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** The 42 cells of one month, Monday-first. */
export function monthGrid({ year, month }: YearMonth): CalendarCell[] {
  const first = new Date(Date.UTC(year, month - 1, 1));
  // getUTCDay: Sunday 0 .. Saturday 6; a Monday-first grid leads with
  // (day + 6) % 7 out-of-month cells.
  const leading = (first.getUTCDay() + 6) % 7;
  const cells: CalendarCell[] = [];
  for (let offset = 0; offset < 42; offset += 1) {
    const day = new Date(Date.UTC(year, month - 1, 1 + offset - leading));
    cells.push({ date: toIsoDate(day), inMonth: day.getUTCMonth() === month - 1 });
  }
  return cells;
}

export function addMonths({ year, month }: YearMonth, delta: number): YearMonth {
  const shifted = new Date(Date.UTC(year, month - 1 + delta, 1));
  return { year: shifted.getUTCFullYear(), month: shifted.getUTCMonth() + 1 };
}

export function yearMonthOf(isoDate: string): YearMonth {
  const [year, month] = isoDate.split("-");
  return { year: Number(year), month: Number(month) };
}

/** Whether `a` is the same calendar month as `b` or a later one. */
export function isSameOrAfterMonth(a: YearMonth, b: YearMonth): boolean {
  return a.year > b.year || (a.year === b.year && a.month >= b.month);
}

/** Inclusive on both ends; ISO strings order lexicographically. */
export function inRange(date: string, from: string, to: string): boolean {
  return date >= from && date <= to;
}
