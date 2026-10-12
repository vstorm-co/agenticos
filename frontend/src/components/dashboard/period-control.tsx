"use client";

import { CalendarRange } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  DateRangePicker,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import {
  customPeriod,
  PERIOD_PRESETS,
  resolvePreset,
  type Period,
  type PeriodPreset,
} from "@/lib/dashboard/period";
import { cn } from "@/lib/utils";

import { SEGMENTED_CLASS, segment } from "./segmented";

/**
 * The time-window strip: the presets and the custom-range calendar, one shape
 * on every page that windows itself. Extracted from the dashboard's FilterRow
 * so the Activity page asks about time in the same vocabulary - one control,
 * one URL form, one set of labels.
 *
 * On a phone the six presets are a select beside the calendar button: as a
 * strip they ran past the screen's edge, cut mid-word at "Last 90 d", with
 * nothing to say the rest were a swipe away.
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
    <>
      <div
        className={cn(SEGMENTED_CLASS, "max-sm:hidden")}
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
        <CustomRange period={period} onChange={onChange} />
      </div>

      <div className="flex min-w-0 items-center gap-2 sm:hidden">
        <Select
          value={period.preset === "custom" ? undefined : period.preset}
          onValueChange={(next) => {
            const preset = PERIOD_PRESETS.find((option) => option === next);
            if (preset) onChange(resolvePreset(preset));
          }}
        >
          <SelectTrigger className="h-9 w-auto min-w-36" aria-label={t("period.label")}>
            <SelectValue placeholder={t("period.custom")} />
          </SelectTrigger>
          <SelectContent>
            {PERIOD_PRESETS.map((preset) => (
              <SelectItem key={preset} value={preset}>
                {t(`period.${preset}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className={SEGMENTED_CLASS}>
          <CustomRange period={period} onChange={onChange} />
        </div>
      </div>
    </>
  );
}

function CustomRange({ period, onChange }: { period: Period; onChange: (period: Period) => void }) {
  const t = useTranslations("dashboard");
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-pressed={period.preset === "custom"}
          className={segment(period.preset === "custom")}
        >
          <CalendarRange className="size-3.5" aria-hidden />
          {period.preset === "custom" ? `${period.from} – ${period.to}` : t("period.custom")}
        </button>
      </PopoverTrigger>
      {/* Bounded by the room the screen has: the two-month calendar is taller
          than what is left below the strip on a phone, and ran off its foot. */}
      <PopoverContent
        align="start"
        collisionPadding={8}
        className="max-h-[var(--radix-popover-content-available-height)] w-auto overflow-y-auto p-4"
      >
        <DateRangePicker
          value={period.preset === "custom" ? { from: period.from, to: period.to } : null}
          onChange={(range) => onChange(customPeriod(range.from, range.to))}
        />
      </PopoverContent>
    </Popover>
  );
}
