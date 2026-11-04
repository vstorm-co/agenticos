"use client";

import { ArrowDown, ArrowDownUp, ArrowUp } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  Button,
  Label,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { UNSORTABLE_TYPES, type ColumnDef, type RecordSort } from "@/types/tables";
import { ColumnTypeIcon } from "./column-type-icon";

/** Server-side ordering shared by the grid, list and every Kanban lane. */
export function RecordSortPopover({
  columns,
  sort,
  onChange,
}: {
  columns: ColumnDef[];
  sort: RecordSort;
  onChange: (sort: RecordSort) => void;
}) {
  const t = useTranslations("tables.sorting");
  const metadata = useTranslations("tables.markdown");
  const offered = columns.filter(
    (column) =>
      !column.archived &&
      (column.system
        ? column.system === "created_at" || column.system === "updated_at"
        : !UNSORTABLE_TYPES.has(column.type)),
  );
  const key = (column: ColumnDef) => column.system ?? column.id;
  const label = (column: ColumnDef) =>
    column.system === "created_at"
      ? metadata("createdAt")
      : column.system === "updated_at"
        ? metadata("updatedAt")
        : column.label;
  const current = offered.find((column) => key(column) === sort.by);
  const isDefault = sort.by === "created_at" && sort.direction === "asc";
  const Direction = sort.direction === "asc" ? ArrowUp : ArrowDown;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant={isDefault ? "outline" : "secondary"}
          size="sm"
          className="gap-2"
          data-tour="table-sort"
          aria-label={
            !isDefault && current
              ? t("active", {
                  column: label(current),
                  direction: t(sort.direction === "asc" ? "ascending" : "descending"),
                })
              : t("title")
          }
        >
          <ArrowDownUp className="size-4" />
          {t("title")}
          {!isDefault && current && (
            <span className="text-muted-foreground flex min-w-0 items-center gap-1 text-xs">
              <span className="max-w-28 truncate">{label(current)}</span>
              <Direction aria-hidden="true" className="size-3 shrink-0" />
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 max-w-[calc(100vw-2rem)] space-y-4 p-4">
        <div className="space-y-1">
          <h3 className="text-sm font-semibold">{t("title")}</h3>
          <p className="text-muted-foreground text-xs">{t("description")}</p>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="record-sort-column">{t("column")}</Label>
          <Select value={sort.by} onValueChange={(by) => onChange({ ...sort, by })}>
            <SelectTrigger id="record-sort-column">
              <SelectValue placeholder={t("chooseColumn")} />
            </SelectTrigger>
            <SelectContent>
              {offered.map((column) => (
                <SelectItem key={key(column)} value={key(column)}>
                  <span className="flex items-center gap-2">
                    <ColumnTypeIcon type={column.type} />
                    {label(column)}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="record-sort-direction">{t("direction")}</Label>
          <Select
            value={sort.direction}
            onValueChange={(direction) => {
              if (direction === "asc" || direction === "desc") onChange({ ...sort, direction });
            }}
          >
            <SelectTrigger id="record-sort-direction">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="asc">
                <span className="flex items-center gap-2">
                  <ArrowUp className="size-3.5" />
                  {t("ascending")}
                </span>
              </SelectItem>
              <SelectItem value="desc">
                <span className="flex items-center gap-2">
                  <ArrowDown className="size-3.5" />
                  {t("descending")}
                </span>
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="w-full"
          disabled={isDefault}
          onClick={() => onChange({ by: "created_at", direction: "asc" })}
        >
          {t("reset")}
        </Button>
      </PopoverContent>
    </Popover>
  );
}
