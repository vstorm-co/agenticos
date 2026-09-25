"use client";

import { create } from "zustand";

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

/** The inner map's key for a whole-row conflict (`fieldId: null`) - never a real column id. */
const ROW_CONFLICT_KEY = "";

function conflictKey(fieldId: string | null): string {
  return fieldId ?? ROW_CONFLICT_KEY;
}

interface TableViewStoreState {
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
 * Ephemeral table-editing state: nothing here is server data.
 *
 * The conflict banners a stale `expected_revision` leaves behind, keyed by
 * record id, so one table's banners never show on another's records. A session
 * reset (`session-reset.ts`) clears them all.
 */
export const useTableViewStore = create<TableViewStoreState>((set) => ({
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
  reset: () => set({ conflicts: {} }),
}));
