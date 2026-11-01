"use client";

import { useTranslations } from "next-intl";
import { Eye, EyeOff } from "lucide-react";

import { Button, Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import type { ColumnDef } from "@/types/tables";

/**
 * The columns this screen hides, and the way back to each: a hidden column has
 * no header left to open a menu from.
 */
export function HiddenColumnsPopover({
  hidden,
  onShow,
  onShowAll,
}: {
  hidden: ColumnDef[];
  onShow: (column: ColumnDef) => void;
  onShowAll: () => void;
}) {
  const t = useTranslations("tables.columnMenu");
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm">
          <EyeOff className="h-4 w-4" /> {t("hiddenCount", { count: hidden.length })}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-60 p-1.5">
        {hidden.map((column) => (
          <button
            key={column.id}
            type="button"
            className="hover:bg-accent flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm"
            onClick={() => onShow(column)}
          >
            <span className="truncate">{column.label}</span>
            <Eye aria-hidden="true" className="text-muted-foreground size-4" />
          </button>
        ))}
        <div className="border-border mt-1 border-t pt-1">
          <Button variant="ghost" size="sm" className="w-full justify-start" onClick={onShowAll}>
            {t("showAll")}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
