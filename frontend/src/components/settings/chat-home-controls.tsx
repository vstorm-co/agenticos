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
import {
  CHAT_HOME_ITEMS,
  type ChatHomeItem,
  type ChatHomeOptions,
  type ChatHomeOverrides,
} from "@/lib/console-experience-api";

/** Four separate choices, with inherited values named and deployment restrictions explained. */
export function ChatHomeControls({
  mode,
  value,
  defaults,
  availability,
  disabled = false,
  onChange,
}: {
  mode: "availability" | "inheritance";
  value: ChatHomeOverrides | null | undefined;
  defaults?: ChatHomeOptions;
  availability?: ChatHomeOptions;
  disabled?: boolean;
  onChange: (field: ChatHomeItem, value: boolean | null) => void;
}) {
  const t = useTranslations("consoleExperience");
  const id = useId();
  return (
    <div className="divide-border divide-y">
      {CHAT_HOME_ITEMS.map((field) => {
        const allowed = availability?.[field] !== false;
        const inherited = defaults?.[field] !== false;
        const fieldId = `${id}-${field}`;
        return (
          <div
            key={field}
            className="flex flex-col gap-3 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between"
          >
            <div className="min-w-0 space-y-1">
              <Label htmlFor={fieldId}>{t(`items.${field}.label`)}</Label>
              <p id={`${fieldId}-hint`} className="text-muted-foreground text-xs leading-5">
                {t(`items.${field}.hint`)}
              </p>
              {!allowed && <p className="text-muted-foreground text-xs">{t("unavailable")}</p>}
            </div>
            {mode === "availability" ? (
              <Switch
                id={fieldId}
                checked={value?.[field] !== false}
                disabled={disabled}
                onCheckedChange={(next) => onChange(field, next)}
                aria-describedby={`${fieldId}-hint`}
              />
            ) : (
              <Select
                value={
                  value?.[field] === null || value?.[field] === undefined
                    ? "inherit"
                    : value[field]
                      ? "show"
                      : "hide"
                }
                disabled={disabled || !allowed}
                onValueChange={(next) =>
                  onChange(field, next === "inherit" ? null : next === "show")
                }
              >
                <SelectTrigger
                  id={fieldId}
                  className="w-full shrink-0 sm:w-56"
                  aria-describedby={`${fieldId}-hint`}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="inherit">
                    {t(inherited ? "inheritShown" : "inheritHidden")}
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
