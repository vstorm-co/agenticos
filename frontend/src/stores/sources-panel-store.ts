"use client";

import { create, createStore, type StateCreator } from "zustand";

import { scopedStore } from "./chat-scope-context";
import type { SourceItem } from "@/lib/chat-sources";

export interface SourcesPanelState {
  isOpen: boolean;
  sources: SourceItem[];
  highlightedIndex: number | null;
  messageId: string | null;
  open: (
    sources: SourceItem[],
    highlightedIndex?: number | null,
    messageId?: string | null,
  ) => void;
  toggle: (messageId: string, sources: SourceItem[]) => void;
  close: () => void;
}

const sourcesPanelState: StateCreator<SourcesPanelState> = (set) => ({
  isOpen: false,
  sources: [],
  highlightedIndex: null,
  messageId: null,
  open: (sources, highlightedIndex = null, messageId = null) =>
    set({ isOpen: true, sources, highlightedIndex, messageId }),
  toggle: (messageId, sources) =>
    set((state) =>
      state.isOpen && state.messageId === messageId
        ? { isOpen: false, highlightedIndex: null, messageId: null }
        : { isOpen: true, sources, highlightedIndex: null, messageId },
    ),
  close: () => set({ isOpen: false, highlightedIndex: null, messageId: null }),
});

/** A copy of its own, for a conversation in a scope - see `ChatScope`. */
export const createSourcesPanelStore = () => createStore<SourcesPanelState>()(sourcesPanelState);

export const useSourcesPanelStore = scopedStore(
  create<SourcesPanelState>()(sourcesPanelState),
  (scope) => scope.sourcesPanel,
);
