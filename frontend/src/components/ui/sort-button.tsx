"use client";

import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type SortDirection = "asc" | "desc";

interface SortButtonProps {
  /** Whether the table is currently sorted by this column. */
  active: boolean;
  direction: SortDirection;
  onClick: () => void;
  children: ReactNode;
}

/**
 * A column header that sorts. Lives in `ui/` and knows nothing about any page.
 *
 * Extracted from `admin/conversations`, which had it as a local component, at the
 * point Activity needed the same control - so the second user is the reason it is
 * shared rather than a second copy. A table primitive for the whole product is
 * proposed separately (#139); this is the piece of it that two pages already
 * need, put where that work can absorb it instead of finding it twice.
 *
 * Three states rather than two: `ArrowUpDown` when the table is sorted by
 * something else, so a reader can tell "sortable" from "sorted ascending" at a
 * glance. `aria-sort` carries the same thing for a screen reader, on the `th`
 * `DataTable` renders this into - which is why the accessible name here is the
 * column's own label, not the state: an `aria-label` naming the state made
 * every sort control on a table answer to the same name.
 */
export function SortButton({ active, direction, onClick, children }: SortButtonProps) {
  const t = useTranslations("ui");
  const Icon = !active ? ArrowUpDown : direction === "asc" ? ArrowUp : ArrowDown;
  const label = !active
    ? t("sortBy")
    : direction === "asc"
      ? t("sortedAscending")
      : t("sortedDescending");

  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      className={cn(
        "hover:text-foreground inline-flex items-center gap-1 text-left uppercase transition-colors",
        active && "text-foreground",
      )}
    >
      {children}
      <Icon className={cn("h-3 w-3", !active && "opacity-40")} aria-hidden />
    </button>
  );
}
