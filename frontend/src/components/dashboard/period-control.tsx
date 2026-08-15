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
    <div className="flex flex-wrap items-center gap-1" role="group" aria-label={t("period.label")}>
      {PERIOD_PRESETS.map((preset: PeriodPreset) => (
        <button
          key={preset}
          type="button"
          aria-pressed={period.preset === preset}
          onClick={() => onChange(resolvePreset(preset))}
          className={cn(
            "rounded-md px-2.5 py-1 text-xs",
            period.preset === preset
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:bg-accent hover:text-foreground",
          )}
        >
          {t(`period.${preset}`)}
        </button>
      ))}
      <Popover>
        <PopoverTrigger asChild>
          <button
            type="button"
            aria-pressed={period.preset === "custom"}
            className={cn(
              "flex items-center gap-1 rounded-md px-2.5 py-1 text-xs",
              period.preset === "custom"
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-accent hover:text-foreground",
            )}
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
