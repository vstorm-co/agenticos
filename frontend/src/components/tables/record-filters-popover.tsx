"use client";

import { useTranslations } from "next-intl";
import { ListFilter, Plus, X } from "lucide-react";

import {
  type FilterChoice,
  choiceOf,
  choicesFor,
  isComplete,
  newFilter,
  withChoice,
} from "./record-filters";
import { MultiSelectCell } from "./multi-select-cell";
import { RecordCellEditor } from "./record-cell-editor";
import {
  Button,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { CellValue, ColumnDef, RecordFilter } from "@/types/tables";

const DATED = new Set(["date", "datetime"]);

/** The operand control a condition needs, or nothing for "is empty" and "is not empty". */
function Operand({
  id,
  column,
  filter,
  onChange,
}: {
  id: string;
  column: ColumnDef;
  filter: RecordFilter;
  onChange: (value: CellValue | CellValue[]) => void;
}) {
  const t = useTranslations("tables.cells");
  if (filter.op === "is_null") return null;
  if (filter.op === "in") {
    return (
      <MultiSelectCell
        id={id}
        options={column.options}
        value={Array.isArray(filter.value) ? (filter.value as string[]) : []}
        onChange={onChange}
      />
    );
  }
  if (column.type === "boolean") {
    return (
      <Select
        value={String(filter.value === true)}
        onValueChange={(next) => onChange(next === "true")}
      >
        <SelectTrigger aria-label={column.label}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="true">{t("true")}</SelectItem>
          <SelectItem value="false">{t("false")}</SelectItem>
        </SelectContent>
      </Select>
    );
  }
  // A multi-select's `contains` names one option, so it is picked like a single one.
  const asColumn: ColumnDef = {
    ...column,
    type: column.type === "multi_select" ? "single_select" : column.type,
    nullable: true,
  };
  return (
    <RecordCellEditor
      column={asColumn}
      value={(filter.value ?? null) as CellValue}
      onChange={onChange}
      placeholder={t("value")}
    />
  );
}

/**
 * The conditions a view narrows its records by, all of which must hold: a
 * column, an operator its type supports, and an operand typed as the column is.
 *
 * Every row is kept while it is being written; only a complete one is sent, so
 * picking a column does not empty the grid before the value is typed.
 */
export function RecordFiltersPopover({
  columns,
  filters,
  onChange,
}: {
  /** The table's live columns - the ones a condition may name. */
  columns: ColumnDef[];
  filters: RecordFilter[];
  onChange: (filters: RecordFilter[]) => void;
}) {
  const t = useTranslations("tables.filters");
  const byId = new Map(columns.map((column) => [column.id, column]));
  const active = filters.filter(isComplete).length;
  const first = columns[0];

  const replace = (index: number, next: RecordFilter) =>
    onChange(filters.map((filter, at) => (at === index ? next : filter)));
  const opLabel = (column: ColumnDef, choice: FilterChoice) =>
    DATED.has(column.type) && t.has(`opDated.${choice}`)
      ? t(`opDated.${choice}`)
      : t(`op.${choice}`);

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm">
          <ListFilter className="h-4 w-4" /> {t("button")}
          {active > 0 && (
            <span className="bg-foreground text-background rounded-full px-1.5 text-[11px] font-medium tabular-nums">
              {active}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[min(40rem,calc(100vw-2rem))] p-0">
        <div className="border-border border-b px-4 py-3">
          <p className="text-sm font-medium">{t("title")}</p>
          <p className="text-muted-foreground text-xs">{t("hint")}</p>
        </div>
        <div className="max-h-[50vh] space-y-2 overflow-y-auto p-3">
          {filters.length === 0 && (
            <p className="text-muted-foreground px-1 py-3 text-center text-sm">{t("none")}</p>
          )}
          {filters.map((filter, index) => {
            const column = byId.get(filter.column_id);
            // A condition on a column since archived cannot be edited, only removed.
            if (!column) return null;
            return (
              <div key={index} className="flex items-start gap-2">
                <span className="text-muted-foreground w-10 shrink-0 pt-2 text-right text-xs">
                  {index === 0 ? t("where") : t("and")}
                </span>
                <Select
                  value={column.id}
                  onValueChange={(id) => replace(index, newFilter(byId.get(id) as ColumnDef))}
                >
                  <SelectTrigger className="w-40 shrink-0" aria-label={t("column")}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {columns.map((option) => (
                      <SelectItem key={option.id} value={option.id}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select
                  value={choiceOf(filter)}
                  onValueChange={(choice) =>
                    replace(index, withChoice(filter, column, choice as FilterChoice))
                  }
                >
                  <SelectTrigger className="w-36 shrink-0" aria-label={t("operator")}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {choicesFor(column).map((choice) => (
                      <SelectItem key={choice} value={choice}>
                        {opLabel(column, choice)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <div className="min-w-0 flex-1">
                  <Operand
                    id={`filter-${index}`}
                    column={column}
                    filter={filter}
                    onChange={(value) => replace(index, { ...filter, value })}
                  />
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="text-muted-foreground size-9 shrink-0"
                  aria-label={t("remove")}
                  onClick={() => onChange(filters.filter((_, at) => at !== index))}
                >
                  <X className="size-4" />
                </Button>
              </div>
            );
          })}
        </div>
        <div className="border-border flex items-center justify-between border-t px-3 py-2">
          <Button
            variant="ghost"
            size="sm"
            disabled={!first}
            onClick={() => onChange([...filters, newFilter(first as ColumnDef)])}
          >
            <Plus className="h-4 w-4" /> {t("add")}
          </Button>
          {filters.length > 0 && (
            <Button variant="ghost" size="sm" onClick={() => onChange([])}>
              {t("clear")}
            </Button>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
