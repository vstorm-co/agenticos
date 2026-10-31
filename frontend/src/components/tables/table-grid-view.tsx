"use client";

import { useTableDisplay } from "./table-display-context";

import { RecordSourceBadge } from "./record-source-badge";
import { markdownDocument } from "@/lib/markdown-document";

import { type KeyboardEvent, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Check, PanelRightOpen, Plus, Trash2, Lock, FileText } from "lucide-react";

import { type ColumnActions, ColumnHeaderMenu } from "./column-header-menu";
import { ColumnTypeIcon, isNumeric } from "./column-type-icon";
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
import { recordCellText } from "@/lib/format-cell-value";
import { cn } from "@/lib/utils";
import { useTableViewStore } from "@/stores";
import {
  COMPUTED_TYPES,
  UNSORTABLE_TYPES,
  type CellValue,
  type ColumnDef,
  type RecordRead,
  type RecordSort,
} from "@/types/tables";

/** A cell's fixed 52px (`h-13`) and the row's bottom border. */
const ROW_HEIGHT = 53;

interface EditingCell {
  recordId: string;
  columnId: string;
}

/** A yes/no as a checkbox reads in a sheet: ticked or empty, its word for a screen reader. */
function BoolMark({ on, label }: { on: boolean; label: string }) {
  return (
    <span
      className={cn(
        "inline-flex size-4 items-center justify-center rounded border align-middle",
        on ? "border-foreground bg-foreground text-background" : "border-input",
      )}
    >
      {on && <Check aria-hidden="true" className="size-3" />}
      <span className="sr-only">{label}</span>
    </span>
  );
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
  recordColumns = columns,
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
  /** Full schema for validating quick creation, including hidden required fields. */
  recordColumns?: ColumnDef[];
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
  const locale = useLocale();
  const preferences = useTableDisplay();
  const tGrid = useTranslations("tables.grid");
  const tMetadata = useTranslations("tables.markdown");
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
    if (column.system === "created_by" || column.system === "updated_by") {
      return (
        <RecordSourceBadge
          principalId={record[column.system]}
          source={column.system === "created_by" ? record.created_source : record.updated_source}
        />
      );
    }
    if (column.type === "rich_text") {
      const source = record.values[column.id];
      const title =
        typeof source === "string"
          ? markdownDocument(source)
              .body.split("\n")
              .find((line) => line.trim())
              ?.replace(/^#{1,6}\s+/, "")
          : null;
      return title ? (
        <span className="flex max-w-72 items-center gap-2">
          <FileText className="text-muted-foreground size-3.5 shrink-0" />
          <span className={preferences.wrap_text ? "break-words whitespace-pre-wrap" : "truncate"}>
            {title}
          </span>
        </span>
      ) : (
        <span className="text-muted-foreground">—</span>
      );
    }
    const value = record.values[column.id] ?? null;
    if (column.type === "boolean" && typeof value === "boolean") {
      return <BoolMark on={value} label={boolLabel(value)} />;
    }
    const chips = selectChips(column, value);
    if (chips)
      return (
        <span
          className={cn(
            "flex max-w-60",
            !preferences.wrap_text &&
              "max-h-7 overflow-hidden whitespace-nowrap [&>span]:flex-nowrap",
          )}
        >
          {chips}
        </span>
      );
    const text = recordCellText(column, record, boolLabel, locale, preferences);
    return (
      <span
        className={cn(
          "block max-w-60 min-w-32",
          preferences.wrap_text ? "break-words whitespace-pre-wrap" : "truncate",
        )}
        title={text}
      >
        {text || "—"}
      </span>
    );
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
    // A worked-out column is read, never edited: what it shows comes from its link.
    if (!canEdit || column.system || COMPUTED_TYPES.has(column.type))
      return display(column, record);
    const value = record.values[column.id] ?? null;
    if (editing?.recordId === record.id && editing.columnId === column.id) {
      return (
        <InlineCell
          column={column}
          value={value}
          links={record.links?.[column.id]}
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
        className={cn(
          "hover:bg-accent/60 focus-visible:ring-ring -mx-4 -my-3 block min-h-11 w-[calc(100%+2rem)] px-4 py-3 focus-visible:ring-1 focus-visible:outline-none focus-visible:ring-inset",
          isNumeric(column.type) ? "text-right" : "text-left",
        )}
        onClick={(event) => {
          event.stopPropagation();
          // A yes/no that cannot be empty has one edit to make: the other one.
          if (column.type === "boolean" && !column.nullable) {
            writeCell(record, column.id, value !== true);
            return;
          }
          if (column.type === "rich_text") {
            onOpenRecord(record);
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
    key: column.system ?? column.id,
    header:
      columnActions && !column.system ? (
        <ColumnHeaderMenu column={column} sort={sort} actions={columnActions} />
      ) : (
        <span className="inline-flex items-center gap-1.5">
          {column.system ? (
            <Lock className="text-muted-foreground size-3.5" />
          ) : (
            <ColumnTypeIcon type={column.type} />
          )}
          {column.system
            ? tMetadata(
                {
                  created_at: "createdAt",
                  updated_at: "updatedAt",
                  created_by: "createdBy",
                  updated_by: "updatedBy",
                }[column.system],
              )
            : column.label}
        </span>
      ),
    // Numbers read right-aligned, so their digits line up down the column.
    align: isNumeric(column.type) ? ("right" as const) : undefined,
    className: isNumeric(column.type) ? "tabular-nums" : undefined,
    cell: (record) => renderCell(column, record),
    sortable: column.system
      ? column.system.endsWith("_at")
      : !columnActions && !UNSORTABLE_TYPES.has(column.type),
  }));

  if (canEdit) {
    tableColumns.unshift({
      key: "__select",
      className: "bg-card sticky left-0 z-20 w-12 min-w-12 px-3 sm:px-3",
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
    tableColumns.splice(1, 0, {
      key: "__open",
      className: "bg-card sticky left-12 z-20 w-10 min-w-10 px-1 sm:px-1",
      header: <span className="sr-only">{tGrid("openRecord")}</span>,
      cell: (record) => (
        <Button
          variant="ghost"
          size="icon"
          className="text-muted-foreground size-7"
          aria-label={tGrid("openRecord")}
          title={tGrid("openRecord")}
          onClick={() => onOpenRecord(record)}
        >
          <PanelRightOpen className="size-3.5" />
        </Button>
      ),
    });
    if (onAddColumn)
      tableColumns.push({
        key: "__add",
        className: "w-12 px-2",
        header: (
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
        ),
        cell: () => null,
      });
  }

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      {chosen.length > 0 && (
        <div
          role="toolbar"
          aria-label={tGrid("selected", { count: chosen.length })}
          className="border-border bg-popover/95 absolute bottom-5 left-1/2 z-30 flex max-w-[calc(100%-2rem)] -translate-x-1/2 flex-wrap items-center justify-center gap-2 rounded-xl border px-3 py-2 text-sm whitespace-nowrap shadow-lg backdrop-blur"
        >
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
        key={preferences.wrap_text ? "wrapped" : "compact"}
        columns={tableColumns}
        rows={records}
        getRowKey={(record) => record.id}
        loading={isLoading}
        onRowClick={canEdit ? undefined : onOpenRecord}
        isRowActive={canEdit ? (record) => selected.has(record.id) : undefined}
        fillHeight
        afterRows={
          onAddRecord && records.length > 0 ? (
            <NewRecordRow
              tableId={tableId}
              columns={columns}
              allColumns={recordColumns}
              onNeedsMore={onAddRecord}
            />
          ) : undefined
        }
        // Every row is one height, so only the rows in view are drawn.
        className={cn(
          "rounded-none border-0",
          preferences.wrap_text ? "[&_tbody_td]:whitespace-normal" : "[&_tbody_td]:h-[52px]",
        )}
        rowHeight={preferences.wrap_text ? undefined : ROW_HEIGHT}
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
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={tGrid("deleteTitle", { count: chosen.length })}
        description={tGrid("deleteDescription")}
        confirmLabel={tGrid("delete")}
        destructive
        onConfirm={deleteChosen}
      />
    </div>
  );
}
