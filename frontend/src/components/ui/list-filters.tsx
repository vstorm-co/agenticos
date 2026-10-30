"use client";

import { useId, useState, type ReactNode } from "react";
import { ChevronDown, SlidersHorizontal } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

/** Secondary list controls are disclosed on demand at every screen size. */
export function ListFilters({
  active,
  children,
  compact = false,
}: {
  active: number;
  children: ReactNode;
  /** Leave room for search in narrow catalog toolbars. */
  compact?: boolean;
}) {
  const t = useTranslations("common");
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((was) => !was)}
        className="border-border bg-background inline-flex min-h-11 touch-manipulation items-center gap-1.5 rounded-xl border px-3.5 text-sm"
      >
        <SlidersHorizontal className="size-4" aria-hidden />
        <span className={cn(compact && "max-[359px]:sr-only")}>{t("filters")}</span>
        {/* A space for whoever hears the name: "Filters 3", not "Filters3". */}
        {active > 0 && " "}
        {active > 0 && (
          <span className="bg-foreground text-background rounded-full px-1.5 text-xs leading-5 tabular-nums">
            {active}
          </span>
        )}
        <ChevronDown
          className={cn(
            "text-muted-foreground size-4 transition-transform",
            open && "rotate-180",
            compact && "max-[359px]:hidden",
          )}
          aria-hidden
        />
      </button>
      <div id={id} hidden={!open} className={cn(open && "contents")}>
        {children}
      </div>
    </>
  );
}
