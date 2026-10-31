"use client";

import { useLocale, useTranslations } from "next-intl";
import { EmptyState } from "@/components/states";
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
  const tEmpty = useTranslations("pages.tables.detail.emptyRecords");
  const boolLabel = (value: boolean) => (value ? t("true") : t("false"));
  const [title, ...secondary] = columns;

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
            className="hover:bg-accent focus-visible:ring-ring flex w-full flex-col gap-2 px-4 py-4 text-left outline-none focus-visible:ring-2 focus-visible:ring-inset"
          >
            <span className="text-foreground truncate text-sm font-medium">
              {(title && recordCellText(title, record, boolLabel, locale)) || t("unnamedRecord")}
            </span>
            {secondary.length > 0 && (
              <span className="flex min-w-0 flex-wrap gap-x-6 gap-y-1 text-xs">
                {secondary.slice(0, 3).map((column) => {
                  const value = recordCellText(column, record, boolLabel, locale);
                  return value ? (
                    <span key={column.id} className="min-w-0">
                      <span className="text-muted-foreground">{column.label}</span>{" "}
                      <span className="break-words">{value}</span>
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
