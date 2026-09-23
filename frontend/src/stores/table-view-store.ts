"use client";

import { create } from "zustand";
import type { RecordFilter, RecordSort } from "@/types/tables";

/** A view's config while it is being edited, before it is saved (or never saved at all). */
export interface TableViewDraft {
  filters: RecordFilter[];
  sort: RecordSort;
  visibleColumns: string[] | null;
  groupBy: string | null;
}

/**
 * A write refused for a stale `expected_revision`, kept so the UI can offer
 * "reload and reapply" without losing what was typed or dragged.
 */
export interface RecordConflict {
  recordId: string;
  /** The values the refused write attempted. */
  pendingValues: Record<string, unknown>;
  /** Which field to show the banner beside, for a single-cell edit. `null` for a whole-row conflict. */
  fieldId: string | null;
}

export function emptyTableViewDraft(): TableViewDraft {
  return {
    filters: [],
    sort: { by: "created_at", direction: "asc" },
    visibleColumns: null,
    groupBy: null,
  };
}

/** The inner map's key for a whole-row conflict (`fieldId: null`) - never a real column id. */
const ROW_CONFLICT_KEY = "";

function conflictKey(fieldId: string | null): string {
  return fieldId ?? ROW_CONFLICT_KEY;
}

interface TableViewStoreState {
  draft: TableViewDraft;
  setDraft: (draft: TableViewDraft) => void;
  /**
   * Conflicts per record, keyed further by field. A user can have more than one
   * field of the same record in flight at once - the sheet commits each field on
   * its own - so a stale write on one field and a successful write on another must
   * not clobber each other: keying only by record would let the second write's
   * `clearConflict` erase the first field's still-pending banner, or let a second
   * field's own conflict silently replace the first's.
   */
  conflicts: Record<string, Record<string, RecordConflict>>;
  setConflict: (conflict: RecordConflict) => void;
  clearConflict: (recordId: string, fieldId: string | null) => void;
  reset: () => void;
}

/**
 * Ephemeral, per-table-view state: nothing here is server data.
 *
 * The in-progress filter/sort/column-visibility/grouping draft before a view is
 * saved (or a view the caller never saves at all), and the conflict banners a
 * stale `expected_revision` leaves behind. A page switching tables calls
 * `reset()` so a conflict on one table's record does not linger onto another's.
 */
export const useTableViewStore = create<TableViewStoreState>((set) => ({
  draft: emptyTableViewDraft(),
  setDraft: (draft) => set({ draft }),
  conflicts: {},
  setConflict: (conflict) =>
    set((state) => {
      const forRecord = {
        ...state.conflicts[conflict.recordId],
        [conflictKey(conflict.fieldId)]: conflict,
      };
      return { conflicts: { ...state.conflicts, [conflict.recordId]: forRecord } };
    }),
  clearConflict: (recordId, fieldId) =>
    set((state) => {
      const forRecord = state.conflicts[recordId];
      const key = conflictKey(fieldId);
      if (!forRecord || !(key in forRecord)) return state;
      const nextForRecord = { ...forRecord };
      delete nextForRecord[key];
      const nextConflicts = { ...state.conflicts };
      if (Object.keys(nextForRecord).length === 0) delete nextConflicts[recordId];
      else nextConflicts[recordId] = nextForRecord;
      return { conflicts: nextConflicts };
    }),
  reset: () => set({ draft: emptyTableViewDraft(), conflicts: {} }),
}));
