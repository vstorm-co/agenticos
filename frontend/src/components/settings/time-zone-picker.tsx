"use client";

import { useId, useState, type ComponentProps } from "react";
import { Command } from "cmdk";
import { Check, ChevronsUpDown, Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import { COMMAND_ITEM_FOCUS, FORM_CONTROL } from "@/components/ui/control-styles";
import { cn } from "@/lib/utils";

const ZONES = [...new Set(["UTC", ...Intl.supportedValuesOf("timeZone")])];

type Props = Pick<
  ComponentProps<"button">,
  "id" | "aria-invalid" | "aria-describedby" | "disabled"
> & {
  value: string;
  onChange: (zone: string) => void;
  "data-guidance"?: boolean;
};

/** Search IANA names while preserving stored aliases that Intl omits. */
export function TimeZonePicker({ value, onChange, ...props }: Props) {
  const t = useTranslations("pages.settings.agentContext");
  const [open, setOpen] = useState(false);
  const listId = useId();
  const zones = value && !ZONES.includes(value) ? [value, ...ZONES] : ZONES;
  const pick = (zone: string) => {
    onChange(zone);
    setOpen(false);
  };
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          {...props}
          type="button"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          className={cn(
            FORM_CONTROL,
            "flex min-h-10 w-full items-center gap-2 px-3 py-2 text-left text-sm",
          )}
        >
          <span className={cn("min-w-0 flex-1 truncate", !value && "text-muted-foreground")}>
            {value || t("chooseTimeZone")}
          </span>
          <ChevronsUpDown className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[var(--radix-popover-trigger-width)] p-0">
        <Command label={t("searchTimeZones")} defaultValue={value || t("noTimeZone")}>
          <div className="border-border flex items-center gap-2 border-b px-3 py-3">
            <Search className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden />
            <Command.Input
              aria-label={t("searchTimeZones")}
              placeholder={t("searchTimeZones")}
              className="placeholder:text-muted-foreground min-w-0 flex-1 bg-transparent text-sm outline-none"
            />
          </div>
          <Command.List
            id={listId}
            aria-label={t("timeZone")}
            className="max-h-64 scrollbar-thin overflow-y-auto overscroll-contain p-1.5"
          >
            <Command.Empty className="text-muted-foreground px-3 py-6 text-center text-sm">
              {t("noTimeZones")}
            </Command.Empty>
            <Command.Item
              value={t("noTimeZone")}
              onSelect={() => pick("")}
              className={cn(
                COMMAND_ITEM_FOCUS,
                "flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm",
              )}
            >
              <span className="flex-1">{t("noTimeZone")}</span>
              {!value && <Check size={16} aria-hidden />}
            </Command.Item>
            {zones.map((zone) => (
              <Command.Item
                key={zone}
                value={zone}
                onSelect={() => pick(zone)}
                className={cn(
                  COMMAND_ITEM_FOCUS,
                  "flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm",
                )}
              >
                <span className="min-w-0 flex-1 truncate">{zone}</span>
                {value === zone && <Check size={16} aria-hidden />}
              </Command.Item>
            ))}
          </Command.List>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
