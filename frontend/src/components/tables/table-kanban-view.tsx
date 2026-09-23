"use client";

import type { HTMLAttributes } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { AlertTriangle } from "lucide-react";
import {
  Badge,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Skeleton,
} from "@/components/ui";
import { useTableRecords } from "@/hooks";
import { isRevisionConflict, useRecordMutation } from "@/hooks/use-record-mutation";
import { formatCellValue } from "@/lib/format-cell-value";
import { qk } from "@/lib/query-keys";
import { getRecord } from "@/lib/tables-api";
import { useTableViewStore } from "@/stores";
import type { RecordConflict } from "@/stores/table-view-store";
import { useKanbanDrag } from "./use-kanban-drag";
import type { ColumnDef, OptionDef, RecordFilter, RecordRead, RecordSort } from "@/types/tables";

const LANE_PAGE_SIZE = 25;

interface Lane {
  /** `null` for the "no value" lane; a live option's id for a normal lane. */
  optionId: string | null;
  label: string;
  /** The read-only catch-all lane a record holding an archived option lands in. */
  archived?: boolean;
}

function laneFilter(groupBy: string, lane: Lane, archivedOptionIds: string[]): RecordFilter | null {
  if (lane.archived) {
    return archivedOptionIds.length > 0
      ? { column_id: groupBy, op: "in", value: archivedOptionIds }
      : null; // No archived options exist - the lane below skips fetching entirely.
  }
  return lane.optionId === null
    ? { column_id: groupBy, op: "is_null", value: true }
    : { column_id: groupBy, op: "eq", value: lane.optionId };
}

function KanbanCard({
  record,
  titleColumn,
  boolLabel,
  dragProps,
  onOpen,
  conflict,
  onReload,
  onDiscard,
  moveTargets,
  onMoveTo,
  canEdit,
}: {
  record: RecordRead;
  // Always defined: `TableKanbanView` never renders a lane (and so never a
  // card) until `columns` has yielded a `groupByColumn`, which guarantees
  // `columns[0]` exists too.
  titleColumn: ColumnDef;
  boolLabel: (value: boolean) => string;
  dragProps: { draggable: boolean; onDragStart: () => void; onDragEnd: () => void };
  onOpen: () => void;
  conflict: boolean;
  onReload: () => void;
  onDiscard: () => void;
  moveTargets: { id: string | null; label: string }[];
  onMoveTo: (optionId: string | null) => void;
  /** No "Move to" menu for a caller who cannot write - absent, not disabled. */
  canEdit: boolean;
}) {
  const t = useTranslations("tables.kanban");
  const title = formatCellValue(titleColumn, record.values[titleColumn.id] ?? null, boolLabel);

  return (
    <div
      {...dragProps}
      className="border-border bg-card space-y-2 rounded-lg border p-2.5 text-sm shadow-sm"
    >
      <div className="flex items-start justify-between gap-2">
        <button type="button" onClick={onOpen} className="truncate text-left font-medium">
          {title || record.id}
        </button>
        {canEdit && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" aria-label={t("moveTo")}>
                {t("moveToShort")}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {moveTargets.map((target) => (
                <DropdownMenuItem
                  key={target.id ?? "__none__"}
                  onSelect={() => onMoveTo(target.id)}
                >
                  {target.label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
      {conflict && (
        <div className="bg-destructive/10 text-destructive space-y-1.5 rounded-md p-2 text-xs">
          <div className="flex items-center gap-1.5">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            <span>{t("conflict")}</span>
          </div>
          <div className="flex gap-2">
            <button type="button" className="underline" onClick={onReload}>
              {t("reloadAndReapply")}
            </button>
            <button type="button" className="underline" onClick={onDiscard}>
              {t("discard")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function KanbanLane({
  tableId,
  lane,
  baseFilters,
  groupBy,
  sort,
  archivedOptionIds,
  titleColumn,
  boolLabel,
  cardProps,
  laneDropProps,
  onOpenRecord,
  moveTargets,
  onMoveTo,
  onReload,
  onDiscard,
  canEdit,
}: {
  tableId: string;
  lane: Lane;
  baseFilters: RecordFilter[];
  groupBy: string;
  sort: RecordSort;
  archivedOptionIds: string[];
  titleColumn: ColumnDef;
  boolLabel: (value: boolean) => string;
  cardProps: (record: RecordRead) => {
    draggable: boolean;
    onDragStart: () => void;
    onDragEnd: () => void;
  };
  laneDropProps: HTMLAttributes<HTMLDivElement>;
  onOpenRecord: (record: RecordRead) => void;
  moveTargets: { id: string | null; label: string }[];
  onMoveTo: (record: RecordRead, targetOptionId: string | null) => void;
  onReload: (recordId: string) => void;
  onDiscard: (recordId: string) => void;
  canEdit: boolean;
}) {
  const filter = laneFilter(groupBy, lane, archivedOptionIds);
  const skipLane = lane.archived === true && filter === null;
  const filters = filter ? [...baseFilters, filter] : baseFilters;
  const { records, hasMore, isLoading } = useTableRecords(skipLane ? null : tableId, {
    filters,
    sort,
    skip: 0,
    limit: LANE_PAGE_SIZE,
  });
  const t = useTranslations("tables.kanban");
  // The store holds one conflict per record, shared with the record detail
  // sheet - a stale write on some other field of this same record sets a
  // conflict here too. Only a conflict about *this* grouping column is ours
  // to show or reload; anything else belongs to the sheet, which reads
  // `conflict.fieldId` itself for the same reason.
  const conflicts = useTableViewStore((state) => state.conflicts);
  const isGroupingConflict = (recordId: string) => conflicts[recordId]?.[groupBy] !== undefined;

  const noDrag = { draggable: false, onDragStart: () => {}, onDragEnd: () => {} };

  return (
    <div className="flex w-64 shrink-0 flex-col gap-2" {...laneDropProps}>
      <div className="flex items-center justify-between px-1">
        <span className="text-sm font-medium">{lane.label}</span>
        <Badge variant="secondary">{records.length}</Badge>
      </div>
      <div className="min-h-16 space-y-2">
        {isLoading && records.length === 0 && <Skeleton className="h-16 w-full" />}
        {!isLoading && records.length === 0 && (
          <p className="text-muted-foreground px-1 text-xs">{t("empty")}</p>
        )}
        {records.map((record) => (
          <KanbanCard
            key={record.id}
            record={record}
            titleColumn={titleColumn}
            boolLabel={boolLabel}
            dragProps={canEdit && !lane.archived ? cardProps(record) : noDrag}
            onOpen={() => onOpenRecord(record)}
            conflict={isGroupingConflict(record.id)}
            onReload={() => onReload(record.id)}
            onDiscard={() => onDiscard(record.id)}
            moveTargets={moveTargets.filter(
              (target) => target.id !== lane.optionId || lane.archived,
            )}
            onMoveTo={(target) => onMoveTo(record, target)}
            canEdit={canEdit}
          />
        ))}
      </div>
      {hasMore && <p className="text-muted-foreground px-1 text-xs">{t("moreAvailable")}</p>}
    </div>
  );
}

/**
 * The kanban view: one lane per live `single_select` option of `groupBy`, a
 * "no value" lane, and a read-only "Archived" catch-all a record holding an
 * archived option still shows up in - unreachable by drag (dropping there is
 * refused client-side, mirroring the server's own "archived column write
 * refused" rule) but visible, so an archived-option record never simply
 * vanishes from the board.
 */
export function TableKanbanView({
  tableId,
  columns,
  groupByColumnId,
  baseFilters,
  sort,
  onOpenRecord,
  canEdit,
}: {
  tableId: string;
  columns: ColumnDef[];
  groupByColumnId: string;
  baseFilters: RecordFilter[];
  sort: RecordSort;
  onOpenRecord: (record: RecordRead) => void;
  /** No drag, no "Move to" menu, for a caller who cannot write to this table. */
  canEdit: boolean;
}) {
  const t = useTranslations("tables.kanban");
  const tCells = useTranslations("tables.cells");
  const boolLabel = (value: boolean) => (value ? tCells("true") : tCells("false"));
  const groupByColumn = columns.find((column) => column.id === groupByColumnId);
  const { update } = useRecordMutation(tableId);
  const setConflict = useTableViewStore((state) => state.setConflict);
  const clearConflict = useTableViewStore((state) => state.clearConflict);
  const conflicts = useTableViewStore((state) => state.conflicts);
  const queryClient = useQueryClient();

  const { cardProps, laneProps } = useKanbanDrag<RecordRead>((record, targetOptionId) =>
    moveRecord(record, targetOptionId),
  );

  function moveRecord(record: RecordRead, targetOptionId: string | null) {
    update.mutate(
      {
        recordId: record.id,
        data: {
          expected_revision: record.revision,
          values: { [groupByColumnId]: targetOptionId },
        },
      },
      {
        onSuccess: () => clearConflict(record.id, groupByColumnId),
        onError: (error) => {
          if (isRevisionConflict(error)) {
            setConflict({
              recordId: record.id,
              pendingValues: { [groupByColumnId]: targetOptionId },
              fieldId: groupByColumnId,
            });
          }
        },
      },
    );
  }

  /**
   * Refetches the record and retries the same lane move against its fresh
   * revision. Only ever wired to a card's "reload and reapply" button, which
   * renders only while the conflict on that record is about this grouping
   * column - so `pending.pendingValues[groupByColumnId]` is always present,
   * set by nothing but `moveRecord`'s own `onError` below.
   *
   * The conflict is cleared only once the retry move has actually landed -
   * `moveRecord`'s own `onSuccess` does that, and its `onError` re-raises the
   * banner if the retry hits another conflict. Clearing here as soon as the
   * refetch lands would drop the pending move for good the moment either the
   * refetch or the retry itself fails, with no way back to it.
   */
  async function reloadAndReapply(recordId: string) {
    // Only ever invoked while `isGroupingConflict(recordId)` is true, which is
    // exactly `conflicts[recordId]?.[groupByColumnId] !== undefined`.
    const pending = conflicts[recordId]?.[groupByColumnId] as RecordConflict;
    try {
      const fresh = await getRecord(tableId, recordId);
      moveRecord(fresh, pending.pendingValues[groupByColumnId] as string | null);
    } catch {
      // The refetch failed - the conflict (and the pending move) stays put.
    }
  }

  /**
   * Drops the pending move and lets the record land wherever its current
   * server value actually places it. No optimistic move was ever applied
   * client-side, so the record already sits in the lane its last-known state
   * put it in; invalidating every lane's query is what brings that back in
   * line with the row the conflict itself proved had changed server-side.
   */
  function discardConflict(recordId: string) {
    clearConflict(recordId, groupByColumnId);
    void queryClient.invalidateQueries({ queryKey: qk.tables.detail(tableId) });
  }

  if (!groupByColumn || groupByColumn.type !== "single_select") {
    return <p className="text-muted-foreground text-sm">{t("needsGroupingColumn")}</p>;
  }
  // `groupByColumn` was found in `columns`, so `columns` has at least one
  // element and this index is never out of range.
  const titleColumn = columns[0] as ColumnDef;

  const liveOptions: OptionDef[] = groupByColumn.options.filter((option) => !option.archived);
  const archivedOptionIds = groupByColumn.options
    .filter((option) => option.archived)
    .map((option) => option.id);

  const lanes: Lane[] = [
    ...liveOptions.map((option): Lane => ({ optionId: option.id, label: option.label })),
    { optionId: null, label: t("noValue") },
    { optionId: null, label: t("archivedLane"), archived: true },
  ];
  const moveTargets = [
    ...liveOptions.map((option) => ({ id: option.id as string | null, label: option.label })),
    { id: null, label: t("noValue") },
  ];

  return (
    <div className="flex gap-3 overflow-x-auto pb-2">
      {lanes.map((lane) => (
        <KanbanLane
          key={lane.archived ? "__archived__" : (lane.optionId ?? "__none__")}
          tableId={tableId}
          lane={lane}
          baseFilters={baseFilters}
          groupBy={groupByColumnId}
          sort={sort}
          archivedOptionIds={archivedOptionIds}
          titleColumn={titleColumn}
          boolLabel={boolLabel}
          cardProps={cardProps}
          laneDropProps={laneProps(lane.optionId, canEdit && lane.archived !== true)}
          onOpenRecord={onOpenRecord}
          moveTargets={moveTargets}
          onMoveTo={moveRecord}
          onReload={(recordId) => void reloadAndReapply(recordId)}
          onDiscard={discardConflict}
          canEdit={canEdit}
        />
      ))}
    </div>
  );
}
