"use client";

import * as React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  addMonths,
  inRange,
  isSameOrAfterMonth,
  monthGrid,
  yearMonthOf,
  type YearMonth,
} from "@/lib/calendar";
import { cn } from "@/lib/utils";

export interface DateRange {
  /** Inclusive ISO dates. */
  from: string;
  to: string;
}

export interface DateRangePickerProps {
  value: DateRange | null;
  /** Fires on the second click, with the two picks already ordered. */
  onChange: (range: DateRange) => void;
  /** Latest pickable ISO date; later cells are disabled. Defaults to today. */
  maxDate?: string;
  className?: string;
}

const WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

function monthLabel({ year, month }: YearMonth): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month - 1, 1)));
}

/**
 * Two months side by side, Monday-first, range picked with two clicks in
 * either order. Reusable by design: the grid math lives in `lib/calendar`,
 * dates travel as ISO strings, and the component owns nothing but the
 * pending first click and which months are on screen.
 */
export function DateRangePicker({ value, onChange, maxDate, className }: DateRangePickerProps) {
  const t = useTranslations("ui");
  const today = new Date().toISOString().slice(0, 10);
  const latest = maxDate ?? today;
  const [pending, setPending] = React.useState<string | null>(null);
  // Open with the range's end (or the last pickable month) on the right.
  const [visible, setVisible] = React.useState<YearMonth>(() =>
    addMonths(yearMonthOf(value?.to ?? latest), -1),
  );

  const pick = (date: string) => {
    if (pending === null) {
      setPending(date);
      return;
    }
    const [from, to] = pending <= date ? [pending, date] : [date, pending];
    setPending(null);
    onChange({ from, to });
  };

  const highlight = (date: string): boolean => {
    if (pending !== null) return date === pending;
    return value !== null && inRange(date, value.from, value.to);
  };

  // The right-hand month may be the last pickable one, never a later one -
  // advancing is refused once it would push it past.
  const atTheEnd = isSameOrAfterMonth(addMonths(visible, 2), addMonths(yearMonthOf(latest), 1));

  return (
    <div className={cn("select-none", className)}>
      <div className="flex items-center justify-between pb-2">
        <button
          type="button"
          aria-label={t("previousMonths")}
          className="hover:bg-accent rounded-md p-1"
          onClick={() => setVisible((current) => addMonths(current, -1))}
        >
          <ChevronLeft className="size-4" />
        </button>
        <button
          type="button"
          aria-label={t("nextMonths")}
          disabled={atTheEnd}
          className="hover:bg-accent rounded-md p-1 disabled:pointer-events-none disabled:opacity-40"
          onClick={() => setVisible((current) => addMonths(current, 1))}
        >
          <ChevronRight className="size-4" />
        </button>
      </div>
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        {[visible, addMonths(visible, 1)].map((month) => (
          <div key={`${month.year}-${month.month}`}>
            <div className="text-foreground pb-2 text-center text-sm font-medium">
              {monthLabel(month)}
            </div>
            <div className="text-muted-foreground grid grid-cols-7 pb-1 text-center text-[11px]">
              {WEEKDAYS.map((weekday) => (
                <span key={weekday}>{weekday}</span>
              ))}
            </div>
            <div className="grid grid-cols-7 gap-y-0.5">
              {monthGrid(month).map((cell) => {
                if (!cell.inMonth) {
                  // Padding only - a labelled button here would duplicate the
                  // neighbouring month's real cell for the same date.
                  return <span key={cell.date} className="mx-auto size-8" aria-hidden />;
                }
                const disabled = cell.date > latest;
                return (
                  <button
                    key={cell.date}
                    type="button"
                    disabled={disabled}
                    aria-label={cell.date}
                    aria-pressed={!disabled && highlight(cell.date)}
                    className={cn(
                      "mx-auto flex size-8 items-center justify-center rounded-md text-sm",
                      disabled && "text-muted-foreground/40 pointer-events-none",
                      !disabled && "hover:bg-accent",
                      !disabled && highlight(cell.date) && "bg-primary text-primary-foreground",
                    )}
                    onClick={() => pick(cell.date)}
                  >
                    {Number(cell.date.slice(8))}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
