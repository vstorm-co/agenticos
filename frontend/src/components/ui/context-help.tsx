"use client";

import { useState, type ReactNode } from "react";
import { Info } from "lucide-react";
import { useTranslations } from "next-intl";
import { Popover, PopoverContent, PopoverTrigger } from "./popover";

/** Explanatory copy on demand; errors and field requirements stay beside their controls. */
export function ContextHelp({
  children,
  action,
}: {
  children?: ReactNode;
  action?: { label: string; onClick: () => void };
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
          <button
            type="button"
            className="text-foreground hover:bg-accent focus-visible:ring-ring bg-muted mt-3 flex min-h-11 w-full items-center justify-center rounded-lg px-3 py-2 text-sm font-medium outline-none first:mt-0 focus-visible:ring-2"
            onClick={() => {
              setOpen(false);
              action.onClick();
            }}
          >
            {action.label}
          </button>
        )}
      </PopoverContent>
    </Popover>
  );
}
