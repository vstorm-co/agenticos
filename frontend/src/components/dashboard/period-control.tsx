"use client";

import { CalendarRange } from "lucide-react";
import { useTranslations } from "next-intl";

import { DateRangePicker, Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import {
  customPeriod,
  PERIOD_PRESETS,
  resolvePreset,
  type Period,
  type PeriodPreset,
} from "@/lib/dashboard/period";
import { cn } from "@/lib/utils";

/**
 * The time-window strip: the presets and the custom-range calendar, one shape
 * on every page that windows itself. Extracted from the dashboard's FilterRow
 * so the Activity page asks about time in the same vocabulary - one control,
 * one URL form, one set of labels.
 */
export function PeriodControl({
  period,
  onChange,
}: {
  period: Period;
  onChange: (period: Period) => void;
}) {
  const t = useTranslations("dashboard");

  return (
    <div
      // One line that scrolls on a phone wherever it is placed: squeezed, its
      // buttons broke "Last 7 days" over three lines.
      // A segmented control: one pill holding the choices, the chosen one
      // filled in ink. Loose `text-xs` chips with a square-cornered fill read
      // as smaller and squarer than every button beside them.
      className="border-border bg-muted/60 flex w-fit max-w-full shrink-0 scrollbar-none items-center gap-0.5 rounded-full border p-0.5 max-md:overflow-x-auto [&>*]:shrink-0 [&>*]:whitespace-nowrap"
      role="group"
      aria-label={t("period.label")}
    >
      {PERIOD_PRESETS.map((preset: PeriodPreset) => (
        <button
          key={preset}
          type="button"
          aria-pressed={period.preset === preset}
          onClick={() => onChange(resolvePreset(preset))}
          className={segment(period.preset === preset)}
        >
          {t(`period.${preset}`)}
        </button>
      ))}
      <Popover>
        <PopoverTrigger asChild>
          <button
            type="button"
            aria-pressed={period.preset === "custom"}
            className={cn("flex items-center gap-1.5", segment(period.preset === "custom"))}
          >
            <CalendarRange className="size-3.5" aria-hidden />
            {period.preset === "custom" ? `${period.from} – ${period.to}` : t("period.custom")}
          </button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-auto p-4">
          <DateRangePicker
            value={period.preset === "custom" ? { from: period.from, to: period.to } : null}
            onChange={(range) => onChange(customPeriod(range.from, range.to))}
          />
        </PopoverContent>
      </Popover>
    </div>
  );
}

/** One choice on the control: a pill, filled in ink when it is the one chosen. */
function segment(active: boolean): string {
  return cn(
    "h-8 rounded-full px-3.5 text-sm font-medium transition-colors",
    active ? "bg-card text-foreground shadow-card" : "text-muted-foreground hover:text-foreground",
  );
}
