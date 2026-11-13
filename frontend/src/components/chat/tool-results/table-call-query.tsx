"use client";

import { useTranslations } from "next-intl";

import { choiceOf } from "@/components/tables/record-filters";
import { sortTarget, type TableCallQuery } from "@/lib/table-tool-calls";
import type { CellValue, RecordFilter, TableRead } from "@/types/tables";

import { useCellText } from "./table-call-data";

const DATED = new Set(["date", "datetime"]);

function Condition({ filter, table }: { filter: RecordFilter; table: TableRead }) {
  const t = useTranslations("tables.filters");
  const cellText = useCellText();
  const column = table.columns.find((candidate) => candidate.id === filter.column_id);
  const choice = choiceOf(filter);
  const operator =
    column !== undefined &&
    DATED.has(column.type) &&
    (choice === "lt" || choice === "lte" || choice === "gt" || choice === "gte")
      ? t(`opDated.${choice}`)
      : t(`op.${choice}`);
  const operands: CellValue[] =
    choice === "empty" || choice === "not_empty" || filter.value === undefined
      ? []
      : Array.isArray(filter.value) && choice === "in"
        ? (filter.value as CellValue[])
        : [filter.value as CellValue];
  return (
    <li className="flex flex-wrap items-baseline gap-x-1.5 text-xs">
      <span className="text-foreground font-medium">
        {column?.label ?? <span className="font-mono">{filter.column_id}</span>}
      </span>
      <span className="text-muted-foreground">{operator}</span>
      {operands.length > 0 && (
        <span className="text-foreground">
          {operands.map((operand) => cellText(column, operand)).join(", ")}
        </span>
      )}
    </li>
  );
}

/** A query's conditions, order and page size, each column and option by its label. */
export function TableCallQueryView({ query, table }: { query: TableCallQuery; table: TableRead }) {
  const t = useTranslations("chat.tools.tableCall");
  const target = query.sort === null ? null : sortTarget(query.sort.by, table.columns);
  const sortColumn =
    target === null ? null : "column" in target ? target.column.label : t(target.field);
  return (
    <div className="space-y-1.5">
      {query.filters.length === 0 && query.search === null ? (
        <p className="text-muted-foreground text-xs">{t("allRecords")}</p>
      ) : (
        <ul className="space-y-1">
          {query.filters.map((filter, index) => (
            <Condition key={`${filter.column_id}:${index}`} filter={filter} table={table} />
          ))}
          {query.search !== null && (
            <li className="text-xs">{t("search", { text: query.search })}</li>
          )}
        </ul>
      )}
      {(query.sort !== null || query.limit !== null) && (
        <p className="text-muted-foreground text-xs">
          {query.sort !== null &&
            t("sortedBy", {
              column: sortColumn ?? query.sort.by,
              direction: query.sort.direction,
            })}
          {query.sort !== null && query.limit !== null && " · "}
          {query.limit !== null && t("limit", { count: query.limit })}
        </p>
      )}
    </div>
  );
}
