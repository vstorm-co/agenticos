"use client";

import { useTranslations } from "next-intl";
import { Archive, ArrowDown, ArrowUp, ChevronDown, EyeOff, Pencil } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui";
import type { ColumnDef, RecordSort } from "@/types/tables";

export interface ColumnActions {
  onSort: (sort: RecordSort) => void;
  onRename: (column: ColumnDef) => void;
  onHide: (column: ColumnDef) => void;
  onArchive: (column: ColumnDef) => void;
}

/**
 * A column's header for someone who may change the table: its label, which way
 * the grid is sorted by it, and a menu of what can be done with it.
 *
 * Sorting and hiding change only what this screen shows, until the view is
 * saved. Renaming and archiving change the table for everyone, each as one new
 * schema version - the same one the Columns dialog would write. A column's type
 * is not offered: the service never changes it, since the values stored under
 * it would no longer mean what they did.
 */
export function ColumnHeaderMenu({
  column,
  sort,
  actions,
}: {
  column: ColumnDef;
  sort: RecordSort;
  actions: ColumnActions;
}) {
  const t = useTranslations("tables.columnMenu");
  const sortedHere = sort.by === column.id ? sort.direction : null;
  const sortable = column.type !== "multi_select";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="hover:text-foreground data-[state=open]:text-foreground inline-flex items-center gap-1 uppercase outline-none"
        aria-label={t("open", { column: column.label })}
      >
        {column.label}
        {sortedHere === "asc" && <ArrowUp aria-hidden="true" className="size-3" />}
        {sortedHere === "desc" && <ArrowDown aria-hidden="true" className="size-3" />}
        <ChevronDown aria-hidden="true" className="size-3 opacity-60" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-52 normal-case">
        {sortable && (
          <>
            <DropdownMenuItem onSelect={() => actions.onSort({ by: column.id, direction: "asc" })}>
              <ArrowUp className="size-4" /> {t("sortAsc")}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => actions.onSort({ by: column.id, direction: "desc" })}>
              <ArrowDown className="size-4" /> {t("sortDesc")}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
          </>
        )}
        <DropdownMenuItem onSelect={() => actions.onRename(column)}>
          <Pencil className="size-4" /> {t("rename")}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => actions.onHide(column)}>
          <EyeOff className="size-4" /> {t("hide")}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem className="text-destructive" onSelect={() => actions.onArchive(column)}>
          <Archive className="size-4" /> {t("archive")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
