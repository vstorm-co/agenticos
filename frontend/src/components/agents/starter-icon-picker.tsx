"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button, Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import { STARTER_ICONS, STARTER_ICON_IDS } from "@/lib/starter-icons";
import type { StarterIcon } from "@/types/agents";

export function StarterIconPicker({
  value,
  number,
  disabled,
  onChange,
}: {
  value: StarterIcon;
  number: number;
  disabled: boolean;
  onChange: (icon: StarterIcon) => void;
}) {
  const t = useTranslations("agents");
  const ti = useTranslations("starterIcons");
  const [open, setOpen] = useState(false);
  const Icon = STARTER_ICONS[value];
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          aria-label={t("starterIcon", { number })}
          className="h-8 shrink-0 gap-1.5 px-2"
        >
          <Icon className="size-4" aria-hidden />
          <ChevronDown className="text-muted-foreground size-3" aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-56 p-3" aria-label={t("starterIcon", { number })}>
        <div className="grid grid-cols-4 gap-1">
          {STARTER_ICON_IDS.map((id) => {
            const Choice = STARTER_ICONS[id];
            return (
              <Button
                key={id}
                type="button"
                disabled={disabled}
                variant={id === value ? "secondary" : "ghost"}
                size="icon"
                aria-pressed={id === value}
                aria-label={ti(id)}
                title={ti(id)}
                onClick={() => {
                  onChange(id);
                  setOpen(false);
                }}
              >
                <Choice className="size-4" aria-hidden />
              </Button>
            );
          })}
        </div>
      </PopoverContent>
    </Popover>
  );
}
