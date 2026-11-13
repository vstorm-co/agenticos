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
  open: controlled,
  onOpenChange,
}: {
  active: number;
  children: ReactNode;
  /** Leave room for search in narrow catalog toolbars. */
  compact?: boolean;
  /** A parent may reveal a field containing a refused filter. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const t = useTranslations("common");
  const [own, setOwn] = useState(false);
  const open = controlled ?? own;
  const id = useId();
  return (
    <>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => {
          setOwn(!open);
          onOpenChange?.(!open);
        }}
        className={cn(
          "border-input bg-field touch:min-h-11 touch:min-w-11 hover:bg-control-hover focus-visible:outline-foreground/40 inline-flex min-h-9 shrink-0 touch-manipulation items-center justify-center gap-1.5 rounded-lg border px-3 text-[13px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2",
          compact && "max-sm:min-w-11 max-sm:px-2.5",
        )}
      >
        <SlidersHorizontal className="size-4" aria-hidden />
        <span className={cn(compact && "max-sm:sr-only")}>{t("filters")}</span>
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
            compact && "max-sm:hidden",
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
