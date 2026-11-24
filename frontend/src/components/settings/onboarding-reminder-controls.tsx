"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";
import {
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type {
  OnboardingReminderOptions,
  OnboardingReminderOverrides,
} from "@/lib/console-experience-api";

export function OnboardingReminderControls({
  value,
  defaults = { enabled: true, snooze_days: 1 },
  available = true,
  disabled = false,
  onChange,
}: {
  value: OnboardingReminderOverrides | null | undefined;
  defaults?: OnboardingReminderOptions;
  available?: boolean;
  disabled?: boolean;
  onChange: (changes: OnboardingReminderOverrides) => void;
}) {
  const t = useTranslations("consoleExperience");
  const id = useId();
  return (
    <div className="space-y-4">
      {!available && <p className="text-muted-foreground text-xs">{t("unavailable")}</p>}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <Label htmlFor={`${id}-enabled`}>{t("remindersEnabled")}</Label>
        <Select
          value={value?.enabled == null ? "inherit" : value.enabled ? "show" : "hide"}
          disabled={disabled || !available}
          onValueChange={(next) =>
            onChange({ enabled: next === "inherit" ? null : next === "show" })
          }
        >
          <SelectTrigger id={`${id}-enabled`} className="w-full sm:w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="inherit">
              {t(defaults.enabled ? "inheritShown" : "inheritHidden")}
            </SelectItem>
            <SelectItem value="show">{t("show")}</SelectItem>
            <SelectItem value="hide">{t("hide")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <Label htmlFor={`${id}-days`}>{t("remindersFrequency")}</Label>
        <Select
          value={value?.snooze_days == null ? "inherit" : String(value.snooze_days)}
          disabled={disabled || !available}
          onValueChange={(next) => {
            if (next === "inherit") onChange({ snooze_days: null });
            else if (next === "1" || next === "3" || next === "7")
              onChange({ snooze_days: next === "1" ? 1 : next === "3" ? 3 : 7 });
          }}
        >
          <SelectTrigger id={`${id}-days`} className="w-full sm:w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="inherit">
              {t("inheritDays", { count: defaults.snooze_days })}
            </SelectItem>
            {([1, 3, 7] as const).map((count) => (
              <SelectItem key={count} value={String(count)}>
                {t("days", { count })}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
