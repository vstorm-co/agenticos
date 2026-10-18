"use client";

import { create, createStore, type StateCreator } from "zustand";

import { scopedStore } from "./chat-scope-context";
import type { SourceItem } from "@/lib/chat-sources";

export interface SourcesPanelState {
  isOpen: boolean;
  sources: SourceItem[];
  highlightedIndex: number | null;
  open: (sources: SourceItem[], highlightedIndex?: number | null) => void;
  close: () => void;
}

const sourcesPanelState: StateCreator<SourcesPanelState> = (set) => ({
  isOpen: false,
  sources: [],
  highlightedIndex: null,
  open: (sources, highlightedIndex = null) => set({ isOpen: true, sources, highlightedIndex }),
  close: () => set({ isOpen: false, highlightedIndex: null }),
});

/** A copy of its own, for a conversation in a scope - see `ChatScope`. */
export const createSourcesPanelStore = () => createStore<SourcesPanelState>()(sourcesPanelState);

export const useSourcesPanelStore = scopedStore(
  create<SourcesPanelState>()(sourcesPanelState),
  (scope) => scope.sourcesPanel,
);
