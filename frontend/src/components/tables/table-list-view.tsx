"use client";

import { useTableDisplay } from "./table-display-context";

import { useLocale, useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/states";
import { selectChips } from "./option-chip";
import { FileText } from "lucide-react";
import { Skeleton } from "@/components/ui";
import { recordCellText } from "@/lib/format-cell-value";
import type { ColumnDef, RecordRead } from "@/types/tables";

/**
 * One row per record: a title line (the first visible column) plus up to
 * three secondary values, no headers - the simpler surface the issue asks
 * for, where the grid reads badly (a `long_text`-heavy table).
 */
export function TableListView({
  columns,
  records,
  isLoading,
  onOpenRecord,
}: {
  columns: ColumnDef[];
  records: RecordRead[];
  isLoading: boolean;
  onOpenRecord: (record: RecordRead) => void;
}) {
  const t = useTranslations("tables.cells");
  const locale = useLocale();
  const display = useTableDisplay();
  const tEmpty = useTranslations("pages.tables.detail.emptyRecords");
  const boolLabel = (value: boolean) => (value ? t("true") : t("false"));
  const [title, ...rest] = columns;
  const secondary = rest.filter(
    (column) => column.type !== "rich_text" && column.type !== "long_text",
  );

  if (isLoading && records.length === 0) {
    return (
      <div className="space-y-2">
        {[0, 1, 2].map((row) => (
          <Skeleton key={row} className="h-14 w-full" />
        ))}
      </div>
    );
  }

  if (records.length === 0) {
    return <EmptyState title={tEmpty("title")} description={tEmpty("description")} />;
  }

  return (
    <ul className="divide-border divide-y overflow-hidden rounded-lg border">
      {records.map((record) => (
        <li key={record.id}>
          <button
            type="button"
            onClick={() => onOpenRecord(record)}
            className="hover:bg-accent/50 focus-visible:ring-ring flex w-full flex-col gap-2 px-5 py-4 text-left transition-colors outline-none focus-visible:ring-2 focus-visible:ring-inset"
          >
            <span className="text-foreground flex min-w-0 items-center gap-2 text-sm font-medium">
              <FileText className="text-muted-foreground size-4 shrink-0" aria-hidden />
              <span className={display.wrap_text ? "break-words whitespace-pre-wrap" : "truncate"}>
                {(title && recordCellText(title, record, boolLabel, locale, display)) ||
                  t("unnamedRecord")}
              </span>
            </span>
            {secondary.length > 0 && (
              <span className="flex min-w-0 flex-wrap gap-x-6 gap-y-1 text-xs">
                {secondary.slice(0, 3).map((column) => {
                  const value = recordCellText(column, record, boolLabel, locale, display);
                  return value ? (
                    <span key={column.id} className="flex max-w-64 min-w-0 items-center gap-2">
                      <span className="text-muted-foreground">{column.label}</span>{" "}
                      <span
                        className={cn(
                          "min-w-0",
                          display.wrap_text ? "break-words whitespace-pre-wrap" : "truncate",
                        )}
                      >
                        {selectChips(column, record.values[column.id] ?? null) ?? value}
                      </span>
                    </span>
                  ) : null;
                })}
              </span>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}
