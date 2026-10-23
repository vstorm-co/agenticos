"use client";

import { useTranslations } from "next-intl";

import { Label } from "@/components/ui";
import { cn } from "@/lib/utils";

/** How often a schedule runs, as the person picks it first - one of a few, or Custom. */
export type CadenceChoice =
  "every15m" | "hourly" | "every6h" | "daily" | "weekdays" | "weekly" | "custom";

export const CADENCE_CHOICES: readonly CadenceChoice[] = [
  "every15m",
  "hourly",
  "every6h",
  "daily",
  "weekdays",
  "weekly",
  "custom",
];

const LABEL_KEYS: Record<CadenceChoice, string> = {
  every15m: "choiceEvery15m",
  hourly: "choiceHourly",
  every6h: "choiceEvery6h",
  daily: "choiceDaily",
  weekdays: "choiceWeekdays",
  weekly: "choiceWeekly",
  custom: "choiceCustom",
};

export const WORKDAYS: readonly number[] = [1, 2, 3, 4, 5];

/** Whether a set of cron weekdays is exactly Monday to Friday. */
export function isWorkdays(weekdays: readonly number[]): boolean {
  return [...weekdays].sort((a, b) => a - b).join(",") === WORKDAYS.join(",");
}

/** What the cadence controls hold, as far as choosing one of the few is concerned. */
export interface CadenceShape {
  scheduleKind: "interval" | "cron";
  intervalUnit: "minutes" | "hours" | "days";
  intervalCount: string;
  cronFreq: "daily" | "everyNDays" | "weekly" | "monthly" | "advanced";
  cronWeekdays: readonly number[];
}

/**
 * The choice the controls already amount to, or `custom` for anything the few do
 * not name - every 3 hours, monthly, a cron expression. A template's cadence
 * arrives as controls, so this is how it lands on the right choice.
 */
export function chosenCadence(shape: CadenceShape): CadenceChoice {
  if (shape.scheduleKind === "interval") {
    const count = Number(shape.intervalCount);
    if (shape.intervalUnit === "minutes" && count === 15) return "every15m";
    if (shape.intervalUnit === "hours" && count === 1) return "hourly";
    if (shape.intervalUnit === "hours" && count === 6) return "every6h";
    return "custom";
  }
  if (shape.cronFreq === "daily") return "daily";
  if (shape.cronFreq === "weekly") {
    return isWorkdays(shape.cronWeekdays) ? "weekdays" : "weekly";
  }
  return "custom";
}

/**
 * The first question a schedule asks, as one row: a few cadences people mostly
 * want, and Custom for the rest. Only what the choice needs opens under it -
 * a time for a daily run, the days for a weekly one, the whole builder for
 * Custom - instead of presets, two tabs and a repeat menu all at once.
 */
export function CadenceChoices({
  value,
  onChange,
}: {
  value: CadenceChoice;
  onChange: (choice: CadenceChoice) => void;
}) {
  const t = useTranslations("triggers");
  return (
    <div className="space-y-2">
      <Label id="cadence-choices-label">{t("howOften")}</Label>
      <div
        role="radiogroup"
        aria-labelledby="cadence-choices-label"
        className="flex flex-wrap gap-2"
      >
        {CADENCE_CHOICES.map((choice) => {
          const active = choice === value;
          return (
            <button
              key={choice}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => onChange(choice)}
              className={cn(
                "border-input inline-flex rounded-full border px-3 py-1.5 text-sm font-medium transition-colors",
                active
                  ? "bg-foreground text-background border-foreground"
                  : "text-foreground hover:border-foreground/40 hover:bg-accent",
              )}
            >
              {t(LABEL_KEYS[choice])}
            </button>
          );
        })}
      </div>
    </div>
  );
}
