"use client";

import { type KeyboardEvent, useState } from "react";
import { useTranslations } from "next-intl";
import { Maximize2, Plus, Trash2 } from "lucide-react";

import { type ColumnActions, ColumnHeaderMenu } from "./column-header-menu";
import { InlineCell } from "./inline-cell";
import { NewRecordRow } from "./new-record-row";
import { selectChips } from "./option-chip";
import {
  Button,
  Checkbox,
  Column,
  ConfirmDialog,
  DataTable,
  type TableSort,
} from "@/components/ui";
import { EmptyState } from "@/components/states";
import { useDeferredDelete } from "@/hooks/use-deferred-delete";
import { isRevisionConflict, useRecordMutation } from "@/hooks/use-record-mutation";
import { formatCellValue } from "@/lib/format-cell-value";
import { useTableViewStore } from "@/stores";
import type { CellValue, ColumnDef, RecordRead, RecordSort } from "@/types/tables";

/** A cell's fixed 52px (`h-13`) and the row's bottom border. */
const ROW_HEIGHT = 53;

interface EditingCell {
  recordId: string;
  columnId: string;
}

/**
 * The table view: `DataTable` over the active view's live, visible columns.
 *
 * Sorting is server-side (`onSort`, not `defaultSort`): a `multi_select`
 * column is not sortable per the service, so its `Column` simply omits
 * `sortable`.
 *
 * Read-only, a row click opens `record-detail-sheet.tsx`. Editable, a cell
 * click edits that cell in place and the row's expand button opens the sheet;
 * a checkbox column selects rows for deleting together. A cell write that
 * loses to a newer revision opens the sheet on that record, where the refused
 * value waits beside a retry - the same banner a sheet field raises - rather
 * than being dropped with the closed cell.
 */
export function TableGridView({
  tableId,
  columns,
  records,
  isLoading,
  sort,
  onSort,
  onOpenRecord,
  canEdit,
  onAddRecord,
  columnActions,
  onAddColumn,
  onEndReached,
}: {
  tableId: string;
  columns: ColumnDef[];
  records: RecordRead[];
  isLoading: boolean;
  sort: RecordSort;
  onSort: (sort: RecordSort) => void;
  onOpenRecord: (record: RecordRead) => void;
  canEdit: boolean;
  /**
   * Offered from the empty state when records may be added, and from the
   * new-record line under the grid with what was typed there.
   */
  onAddRecord?: (initial?: Record<string, CellValue>) => void;
  /**
   * A menu on each header - sort, rename, hide, archive - for whoever may
   * change the table. The menu sorts, so the header is not a sort button too.
   */
  columnActions?: ColumnActions;
  /** A "+" after the last column, to add one. */
  onAddColumn?: () => void;
  /** Called as the scroll nears the last record, to load the next page. */
  onEndReached?: () => void;
}) {
  const t = useTranslations("tables.cells");
  const tGrid = useTranslations("tables.grid");
  const tEmpty = useTranslations("pages.tables.detail.emptyRecords");
  const boolLabel = (value: boolean) => (value ? t("true") : t("false"));
  const { commit } = useRecordMutation(tableId);
  const deleteLater = useDeferredDelete(tableId);
  const setConflict = useTableViewStore((state) => state.setConflict);

  const [editing, setEditing] = useState<EditingCell | null>(null);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [confirming, setConfirming] = useState(false);

  // Only the rows in view count: a selection made on another page, or of a
  // record since deleted, is not what the bar offers to delete.
  const chosen = records.filter((record) => selected.has(record.id));
  const allChosen = records.length > 0 && chosen.length === records.length;

  const toggle = (recordId: string, on: boolean) => {
    const next = new Set(selected);
    if (on) next.add(recordId);
    else next.delete(recordId);
    setSelected(next);
  };

  const writeCell = (record: RecordRead, columnId: string, value: CellValue) => {
    commit(record, { [columnId]: value }).catch((error: unknown) => {
      // Anything but a conflict was already toasted by `useRecordMutation`.
      if (!isRevisionConflict(error)) return;
      setConflict({ recordId: record.id, pendingValues: { [columnId]: value }, fieldId: columnId });
      onOpenRecord(record);
    });
  };

  const deleteChosen = () => {
    deleteLater(chosen);
    const next = new Set(selected);
    for (const record of chosen) next.delete(record.id);
    setSelected(next);
    setConfirming(false);
  };

  const display = (column: ColumnDef, record: RecordRead) => {
    const value = record.values[column.id] ?? null;
    return selectChips(column, value) ?? (formatCellValue(column, value, boolLabel) || "—");
  };

  /**
   * Arrow keys move between cells the way a spreadsheet's do: to the cell beside,
   * above or below, found by its place in the grid. A row outside what the
   * scroll has drawn yet is not there to move to, so the key does nothing.
   */
  const moveFrom = (event: KeyboardEvent<HTMLButtonElement>, row: number, col: number) => {
    const step: Record<string, [number, number]> = {
      ArrowUp: [-1, 0],
      ArrowDown: [1, 0],
      ArrowLeft: [0, -1],
      ArrowRight: [0, 1],
    };
    const move = step[event.key];
    if (move === undefined) return;
    const grid = event.currentTarget.closest("table");
    const target = grid?.querySelector<HTMLButtonElement>(
      `[data-cell="${row + move[0]}:${col + move[1]}"]`,
    );
    if (target) {
      event.preventDefault();
      target.focus();
    }
  };

  const renderCell = (column: ColumnDef, record: RecordRead) => {
    if (!canEdit) return display(column, record);
    const value = record.values[column.id] ?? null;
    if (editing?.recordId === record.id && editing.columnId === column.id) {
      return (
        <InlineCell
          column={column}
          value={value}
          onCommit={(next) => writeCell(record, column.id, next)}
          onDone={() => setEditing(null)}
        />
      );
    }
    return (
      <button
        type="button"
        data-cell={`${records.indexOf(record)}:${columns.indexOf(column)}`}
        onKeyDown={(event) => moveFrom(event, records.indexOf(record), columns.indexOf(column))}
        aria-label={tGrid("editCell", { column: column.label })}
        className="hover:bg-accent/60 focus-visible:ring-ring -mx-4 -my-3 block min-h-11 w-[calc(100%+2rem)] px-4 py-3 text-left focus-visible:ring-1 focus-visible:outline-none focus-visible:ring-inset"
        onClick={(event) => {
          event.stopPropagation();
          // A yes/no that cannot be empty has one edit to make: the other one.
          if (column.type === "boolean" && !column.nullable) {
            writeCell(record, column.id, value !== true);
            return;
          }
          setEditing({ recordId: record.id, columnId: column.id });
        }}
      >
        {display(column, record)}
      </button>
    );
  };

  const tableColumns: Column<RecordRead>[] = columns.map((column) => ({
    key: column.id,
    header: columnActions ? (
      <ColumnHeaderMenu column={column} sort={sort} actions={columnActions} />
    ) : (
      column.label
    ),
    cell: (record) => renderCell(column, record),
    sortable: !columnActions && column.type !== "multi_select",
  }));

  if (canEdit) {
    tableColumns.unshift({
      key: "__select",
      className: "w-10 pr-0",
      header: (
        <Checkbox
          aria-label={tGrid("selectAll")}
          checked={allChosen ? true : chosen.length > 0 ? "indeterminate" : false}
          disabled={records.length === 0}
          onCheckedChange={(on) =>
            setSelected(on === true ? new Set(records.map((record) => record.id)) : new Set())
          }
        />
      ),
      cell: (record) => (
        <Checkbox
          aria-label={tGrid("selectRow")}
          checked={selected.has(record.id)}
          onCheckedChange={(on) => toggle(record.id, on === true)}
        />
      ),
    });
    tableColumns.push({
      key: "__open",
      className: "w-12 px-2",
      header: onAddColumn ? (
        <Button
          variant="ghost"
          size="icon"
          className="text-muted-foreground size-7"
          aria-label={tGrid("addColumn")}
          title={tGrid("addColumn")}
          onClick={onAddColumn}
        >
          <Plus className="size-3.5" />
        </Button>
      ) : (
        <span className="sr-only">{tGrid("openRecord")}</span>
      ),
      cell: (record) => (
        <Button
          variant="ghost"
          size="icon"
          className="text-muted-foreground size-7"
          aria-label={tGrid("openRecord")}
          title={tGrid("openRecord")}
          onClick={() => onOpenRecord(record)}
        >
          <Maximize2 className="size-3.5" />
        </Button>
      ),
    });
  }

  return (
    <>
      {chosen.length > 0 && (
        <div className="border-border bg-card mb-2 flex items-center gap-3 rounded-lg border px-3 py-1.5 text-sm">
          <span className="tabular-nums">{tGrid("selected", { count: chosen.length })}</span>
          <Button variant="ghost" size="sm" onClick={() => setSelected(new Set())}>
            {tGrid("clearSelection")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="text-destructive ml-auto"
            onClick={() => setConfirming(true)}
          >
            <Trash2 className="size-3.5" /> {tGrid("delete")}
          </Button>
        </div>
      )}
      <DataTable
        columns={tableColumns}
        rows={records}
        getRowKey={(record) => record.id}
        loading={isLoading}
        onRowClick={canEdit ? undefined : onOpenRecord}
        isRowActive={canEdit ? (record) => selected.has(record.id) : undefined}
        fillHeight
        // Every row is one height, so only the rows in view are drawn.
        className="[&_tbody_td]:h-13"
        rowHeight={ROW_HEIGHT}
        onEndReached={onEndReached}
        sort={{ by: sort.by, dir: sort.direction }}
        onSort={(next: TableSort) => onSort({ by: next.by, direction: next.dir })}
        empty={
          <EmptyState
            title={tEmpty("title")}
            description={tEmpty("description")}
            cta={onAddRecord ? { label: tEmpty("add"), onClick: () => onAddRecord() } : undefined}
          />
        }
      />
      {onAddRecord && records.length > 0 && (
        <NewRecordRow tableId={tableId} columns={columns} onNeedsMore={onAddRecord} />
      )}
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={tGrid("deleteTitle", { count: chosen.length })}
        description={tGrid("deleteDescription")}
        confirmLabel={tGrid("delete")}
        destructive
        onConfirm={deleteChosen}
      />
    </>
  );
}
