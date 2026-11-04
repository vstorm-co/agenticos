"use client";

import { useLocale, useTranslations } from "next-intl";

import { Input } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { WorkingHours } from "@/types/auth";

/** ISO weekdays, Monday first. 2024-01-01 was a Monday. */
const WEEKDAYS = [1, 2, 3, 4, 5, 6, 7] as const;
const MONDAY = Date.UTC(2024, 0, 1);
const DAY_MS = 86_400_000;

/** Monday to Friday, nine to five - what an empty field starts from once a day is picked. */
const USUAL_HOURS: WorkingHours = { days: [1, 2, 3, 4, 5], start: "09:00", end: "17:00" };

/**
 * When the person works (#2301): the days as toggles, named by the browser in
 * the console's language, and the hours. No day picked is no working hours -
 * knowledge for the agent only, so leaving it empty costs nothing.
 */
export function WorkingHoursField({
  value,
  onChange,
  id,
  "aria-describedby": describedBy,
}: {
  value: WorkingHours | null;
  onChange: (next: WorkingHours | null) => void;
  /** Injected by `FormField`, so its label and description reach the day toggles. */
  id?: string;
  "aria-describedby"?: string;
}) {
  const t = useTranslations("pages.settings.agentContext");
  const locale = useLocale();
  const dayName = new Intl.DateTimeFormat(locale, { weekday: "short", timeZone: "UTC" });
  const hours = value ?? { ...USUAL_HOURS, days: [] };

  const toggle = (day: number) => {
    const days = hours.days.includes(day)
      ? hours.days.filter((other) => other !== day)
      : [...hours.days, day].sort((a, b) => a - b);
    onChange(days.length ? { ...hours, days } : null);
  };

  return (
    <div className="space-y-2">
      <div
        id={id}
        role="group"
        aria-label={t("workingDays")}
        aria-describedby={describedBy}
        className="flex flex-wrap gap-1.5"
      >
        {WEEKDAYS.map((day) => (
          <button
            key={day}
            type="button"
            aria-pressed={hours.days.includes(day)}
            onClick={() => toggle(day)}
            className={cn(
              "rounded-full px-3 py-1 text-xs font-medium transition-colors",
              hours.days.includes(day)
                ? "bg-foreground text-background"
                : "bg-muted/60 hover:bg-muted text-foreground",
            )}
          >
            {dayName.format(new Date(MONDAY + (day - 1) * DAY_MS))}
          </button>
        ))}
      </div>
      {value && (
        <div className="flex items-center gap-2">
          <Input
            type="time"
            aria-label={t("workStart")}
            value={hours.start}
            onChange={(event) => onChange({ ...hours, start: event.target.value })}
            className="w-32"
          />
          <span className="text-muted-foreground text-xs">-</span>
          <Input
            type="time"
            aria-label={t("workEnd")}
            value={hours.end}
            onChange={(event) => onChange({ ...hours, end: event.target.value })}
            className="w-32"
          />
        </div>
      )}
    </div>
  );
}
