"use client";

import { useId, useState } from "react";
import { Command } from "cmdk";
import { Check, ChevronDown, Globe2, Search } from "lucide-react";
import { useTranslations } from "next-intl";

import { FormField, Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import { COMMAND_ITEM_FOCUS, FORM_CONTROL } from "@/components/ui/control-styles";
import { cn } from "@/lib/utils";

const ZONES = ["UTC", ...Intl.supportedValuesOf("timeZone")];

export function isTimeZone(zone: string): boolean {
  return ZONES.includes(zone);
}

/** Search is a draft; only choosing a known zone changes the schedule. */
export function ZoneField({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const t = useTranslations("triggers");
  const [open, setOpen] = useState(false);
  const popupId = useId();
  const valid = isTimeZone(value);
  return (
    <FormField
      label={t("timeZoneLabel")}
      htmlFor="cron-zone"
      description={t("timeZoneHelp")}
      error={valid ? null : t("timeZoneInvalid")}
    >
      {/* Own the nested scroll lock so the parent dialog does not cancel list gestures. */}
      <Popover modal open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            id="cron-zone"
            type="button"
            role="combobox"
            aria-expanded={open}
            aria-haspopup="dialog"
            aria-controls={popupId}
            aria-invalid={!valid}
            aria-describedby={valid ? "cron-zone-desc" : "cron-zone-err"}
            className={cn(
              FORM_CONTROL,
              "flex h-10 w-full items-center gap-2.5 px-3 text-left text-sm",
            )}
          >
            <Globe2 aria-hidden className="text-muted-foreground size-4 shrink-0" />
            <span className="min-w-0 flex-1 truncate">{value || t("timeZoneLabel")}</span>
            <ChevronDown aria-hidden className="text-muted-foreground size-4 shrink-0" />
          </button>
        </PopoverTrigger>
        <PopoverContent
          id={popupId}
          align="start"
          className="w-[var(--radix-popover-trigger-width)] overflow-hidden p-0"
          style={{ backgroundColor: "var(--color-card)" }}
        >
          <Command
            className="flex max-h-[calc(var(--radix-popover-content-available-height)-2px)] flex-col"
            label={t("searchTimeZones")}
            defaultValue={value}
            filter={(zone, query) =>
              zone
                .replaceAll("_", " ")
                .toLowerCase()
                .includes(query.replaceAll("_", " ").trim().toLowerCase())
                ? 1
                : 0
            }
          >
            <div className="flex shrink-0 items-center gap-2 border-b px-3 py-3">
              <Search aria-hidden className="text-muted-foreground size-4 shrink-0" />
              <Command.Input
                aria-label={t("searchTimeZones")}
                placeholder={t("searchTimeZones")}
                className="placeholder:text-muted-foreground w-full bg-transparent text-sm outline-none"
              />
            </div>
            <Command.List className="max-h-60 min-h-0 touch-pan-y scrollbar-thin overflow-y-auto overscroll-contain p-1.5">
              <Command.Empty className="text-muted-foreground px-3 py-6 text-center text-sm">
                {t("noTimeZones")}
              </Command.Empty>
              {ZONES.map((zone) => (
                <Command.Item
                  key={zone}
                  value={zone}
                  onSelect={() => {
                    onChange(zone);
                    setOpen(false);
                  }}
                  className={cn(
                    COMMAND_ITEM_FOCUS,
                    "flex cursor-pointer items-center justify-between gap-3 rounded-md px-3 py-2.5 text-sm",
                  )}
                >
                  {zone.replaceAll("_", " ")}
                  {zone === value && <Check aria-hidden className="size-4 shrink-0" />}
                </Command.Item>
              ))}
            </Command.List>
          </Command>
        </PopoverContent>
      </Popover>
    </FormField>
  );
}
