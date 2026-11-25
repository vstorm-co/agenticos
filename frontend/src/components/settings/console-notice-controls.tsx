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
  Switch,
} from "@/components/ui";
import type { ConsoleNotices } from "@/lib/console-experience-api";

const FIELDS = ["desktop_install_prompt", "product_notices"] as const;

export function ConsoleNoticeControls({
  value,
  ceiling,
  disabled,
  mode,
  onChange,
}: {
  value: ConsoleNotices | undefined;
  ceiling?: ConsoleNotices;
  disabled: boolean;
  mode: "availability" | "preference";
  onChange: (changes: ConsoleNotices) => void;
}) {
  const id = useId();
  const t = useTranslations("consoleExperience");
  return (
    <div className="space-y-4">
      {FIELDS.map((field) => {
        const available = ceiling?.[field] !== false;
        return (
          <div
            key={field}
            className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"
          >
            <div className="min-w-0 space-y-1">
              <Label htmlFor={`${id}-${field}`}>{t(`presentation.${field}`)}</Label>
              <p id={`${id}-${field}-hint`} className="text-muted-foreground text-xs leading-5">
                {t(`presentation.${field}Hint`)}
              </p>
              {!available && (
                <p className="text-muted-foreground text-xs">{t("presentation.restricted")}</p>
              )}
            </div>
            {mode === "availability" ? (
              <Switch
                id={`${id}-${field}`}
                checked={value?.[field] !== false}
                disabled={disabled || !available}
                aria-describedby={`${id}-${field}-hint`}
                onCheckedChange={(next) => onChange({ [field]: next })}
              />
            ) : (
              <Select
                value={value?.[field] == null ? "inherit" : value[field] ? "show" : "hide"}
                disabled={disabled || !available}
                onValueChange={(next) =>
                  onChange({ [field]: next === "inherit" ? null : next === "show" })
                }
              >
                <SelectTrigger
                  id={`${id}-${field}`}
                  className="w-full shrink-0 sm:w-56"
                  aria-describedby={`${id}-${field}-hint`}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="inherit">
                    {t(available ? "inheritShown" : "inheritHidden")}
                  </SelectItem>
                  <SelectItem value="show">{t("show")}</SelectItem>
                  <SelectItem value="hide">{t("hide")}</SelectItem>
                </SelectContent>
              </Select>
            )}
          </div>
        );
      })}
    </div>
  );
}
