"use client";

import { useTranslations } from "next-intl";
import { EmptyState } from "@/components/states";
import { Skeleton } from "@/components/ui";
import { formatCellValue } from "@/lib/format-cell-value";
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
    <ul className="divide-border divide-y">
      {records.map((record) => (
        <li key={record.id}>
          <button
            type="button"
            onClick={() => onOpenRecord(record)}
            className="hover:bg-accent flex w-full flex-col gap-0.5 px-3 py-2.5 text-left"
          >
            <span className="text-foreground truncate text-sm font-medium">
              {(title && formatCellValue(title, record.values[title.id] ?? null, boolLabel)) ||
                record.id}
            </span>
            {secondary.length > 0 && (
              <span className="text-muted-foreground truncate text-xs">
                {secondary
                  .slice(0, 3)
                  .map((column) =>
                    formatCellValue(column, record.values[column.id] ?? null, boolLabel),
                  )
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}
