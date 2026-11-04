"use client";

import type { ReactNode } from "react";
import { Info } from "lucide-react";
import { useTranslations } from "next-intl";
import { Popover, PopoverContent, PopoverTrigger } from "./popover";

/** Explanatory copy on demand; errors and field requirements stay beside their controls. */
export function ContextHelp({ children }: { children: ReactNode }) {
  const t = useTranslations("common");
  return (
    <Popover>
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
      </PopoverContent>
    </Popover>
  );
}
