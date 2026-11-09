"use client";

import { useTableDisplay } from "./table-display-context";

import { useLocale, useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/states";
import { selectChips } from "./option-chip";
import { ArrowUpRight, FileText } from "lucide-react";
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
  onAddRecord,
}: {
  columns: ColumnDef[];
  records: RecordRead[];
  isLoading: boolean;
  onOpenRecord: (record: RecordRead) => void;
  onAddRecord?: () => void;
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
    return (
      <div className="text-muted-foreground px-4 py-12 text-center text-sm [&>*]:border-0 [&>*]:bg-transparent">
        <EmptyState
          title={tEmpty("title")}
          description={tEmpty("description")}
          cta={onAddRecord ? { label: tEmpty("add"), onClick: onAddRecord } : undefined}
        />
      </div>
    );
  }

  return (
    <ul className="space-y-2 p-3 sm:p-4">
      {records.map((record) => (
        <li key={record.id}>
          <button
            type="button"
            onClick={() => onOpenRecord(record)}
            className="group border-border/60 bg-background/60 hover:border-foreground/15 hover:bg-background focus-visible:ring-ring flex w-full flex-col gap-3 rounded-xl border px-4 py-4 text-left transition-colors outline-none focus-visible:ring-2 focus-visible:ring-inset"
          >
            <span className="text-foreground flex min-w-0 items-center gap-2 text-sm font-medium">
              <span className="bg-foreground/[0.04] text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-lg">
                <FileText className="size-4" aria-hidden />
              </span>
              <span
                className={cn(
                  "min-w-0 flex-1",
                  display.wrap_text ? "break-words whitespace-pre-wrap" : "truncate",
                )}
              >
                {(title && recordCellText(title, record, boolLabel, locale, display)) ||
                  t("unnamedRecord")}
              </span>
              <ArrowUpRight
                className="text-muted-foreground size-4 shrink-0 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
                aria-hidden
              />
            </span>
            {secondary.length > 0 && (
              <span className="flex min-w-0 flex-wrap gap-x-6 gap-y-2 text-xs sm:pl-10">
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
