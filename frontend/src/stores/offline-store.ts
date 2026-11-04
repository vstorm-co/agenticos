"use client";

import { create } from "zustand";

/** The messages one conversation's outbox holds; `null` is a new chat's. */
export interface OutboxCount {
  conversationId: string | null;
  count: number;
}

export interface OfflineState {
  /**
   * When the oldest copy on screen was saved, while the screen shows copies
   * kept on the device rather than answers from the server; null otherwise.
   */
  savedAt: Date | null;
  /** The outboxes holding messages, which the banner names until they are sent. */
  outbox: readonly OutboxCount[];
  servedFromDevice: (savedAt: Date) => void;
  /** The server answers again: what is on screen is its answer. */
  backOnline: () => void;
  setOutbox: (outbox: readonly OutboxCount[]) => void;
  reset: () => void;
}

/** What the offline banner says: since when the screen is a copy, and what waits to be sent. */
export const useOfflineStore = create<OfflineState>((set) => ({
  savedAt: null,
  outbox: [],
  servedFromDevice: (savedAt) =>
    set((state) => ({
      savedAt: state.savedAt !== null && state.savedAt < savedAt ? state.savedAt : savedAt,
    })),
  backOnline: () => set({ savedAt: null }),
  setOutbox: (outbox) => set({ outbox }),
  reset: () => set({ savedAt: null, outbox: [] }),
}));
