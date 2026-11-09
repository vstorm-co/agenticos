"use client";

import { useState, type ReactNode } from "react";
import { Info } from "lucide-react";
import { useTranslations } from "next-intl";
import { Popover, PopoverContent, PopoverTrigger } from "./popover";
import { Button } from "./button";

/** Explanatory copy on demand; errors and field requirements stay beside their controls. */
export function ContextHelp({
  children,
  action,
}: {
  children?: ReactNode;
  action?: { label: string; icon: ReactNode; onClick: () => void };
}) {
  const [open, setOpen] = useState(false);
  const t = useTranslations("common");
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={t("moreInformation")}
          className="text-muted-foreground hover:text-foreground focus-visible:ring-ring touch:size-11 inline-flex size-8 shrink-0 items-center justify-center rounded-md outline-none focus-visible:ring-2"
        >
          <Info className="size-4" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 text-sm leading-relaxed">
        {children}
        {action && (
          <Button
            type="button"
            variant="secondary"
            className="mt-3 min-h-11 w-full first:mt-0"
            onClick={() => {
              setOpen(false);
              action.onClick();
            }}
          >
            {action.icon}
            {action.label}
          </Button>
        )}
      </PopoverContent>
    </Popover>
  );
}
