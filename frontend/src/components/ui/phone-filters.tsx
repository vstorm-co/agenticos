"use client";

import { useState, type ReactNode } from "react";
import { ChevronDown, SlidersHorizontal } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

/**
 * A list's filters on a phone: one button saying how many are set, which
 * opens them where they stand (#2097). Eight selects wrapped into four rows
 * were a quarter of the screen before the first row of the list. From `sm` up
 * they are always out, as they were.
 */
export function PhoneFilters({ active, children }: { active: number; children: ReactNode }) {
  const t = useTranslations("common");
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((was) => !was)}
        className="border-border bg-background inline-flex h-9 items-center gap-1.5 rounded-full border px-3.5 text-sm sm:hidden"
      >
        <SlidersHorizontal className="size-4" aria-hidden />
        {t("filters")}
        {/* A space for whoever hears the name: "Filters 3", not "Filters3". */}
        {active > 0 && " "}
        {active > 0 && (
          <span className="bg-foreground text-background rounded-full px-1.5 text-xs leading-5 tabular-nums">
            {active}
          </span>
        )}
        <ChevronDown
          className={cn("text-muted-foreground size-4 transition-transform", open && "rotate-180")}
          aria-hidden
        />
      </button>
      <div className={cn("contents", !open && "max-sm:hidden")}>{children}</div>
    </>
  );
}
