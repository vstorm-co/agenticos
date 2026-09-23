"use client";

import { useTranslations } from "next-intl";
import { Column, DataTable, type TableSort } from "@/components/ui";
import { EmptyState } from "@/components/states";
import { formatCellValue } from "@/lib/format-cell-value";
import type { ColumnDef, RecordRead, RecordSort } from "@/types/tables";

/**
 * The table view: `DataTable` over the active view's live, visible columns.
 *
 * Sorting is server-side (`onSort`, not `defaultSort`): a `multi_select`
 * column is not sortable per the service, so its `Column` simply omits
 * `sortable`. A row click opens `record-detail-sheet.tsx` - the one editing
 * surface every view type shares - rather than editing in place, which would
 * collide with the sortable headers and keyboard row navigation `DataTable`
 * already gives this view for free.
 */
export function TableGridView({
  columns,
  records,
  isLoading,
  sort,
  onSort,
  onOpenRecord,
}: {
  columns: ColumnDef[];
  records: RecordRead[];
  isLoading: boolean;
  sort: RecordSort;
  onSort: (sort: RecordSort) => void;
  onOpenRecord: (record: RecordRead) => void;
}) {
  const t = useTranslations("tables.cells");
  const tEmpty = useTranslations("pages.tables");
  const boolLabel = (value: boolean) => (value ? t("true") : t("false"));

  const tableColumns: Column<RecordRead>[] = columns.map((column) => ({
    key: column.id,
    header: column.label,
    cell: (record) => formatCellValue(column, record.values[column.id] ?? null, boolLabel) || "—",
    sortable: column.type !== "multi_select",
  }));

  return (
    <DataTable
      columns={tableColumns}
      rows={records}
      getRowKey={(record) => record.id}
      loading={isLoading}
      onRowClick={onOpenRecord}
      fillHeight
      sort={{ by: sort.by, dir: sort.direction }}
      onSort={(next: TableSort) => onSort({ by: next.by, direction: next.dir })}
      empty={<EmptyState title={tEmpty("empty.title")} description={tEmpty("empty.description")} />}
    />
  );
}
