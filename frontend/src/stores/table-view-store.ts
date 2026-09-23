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

interface TableViewStoreState {
  draft: TableViewDraft;
  setDraft: (draft: TableViewDraft) => void;
  /** One active conflict per record - a second stale write on the same record replaces it. */
  conflicts: Record<string, RecordConflict>;
  setConflict: (conflict: RecordConflict) => void;
  clearConflict: (recordId: string) => void;
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
    set((state) => ({ conflicts: { ...state.conflicts, [conflict.recordId]: conflict } })),
  clearConflict: (recordId) =>
    set((state) => {
      const next = { ...state.conflicts };
      delete next[recordId];
      return { conflicts: next };
    }),
  reset: () => set({ draft: emptyTableViewDraft(), conflicts: {} }),
}));
