"use client";

import { create, createStore, type StateCreator } from "zustand";

import { scopedStore } from "./chat-scope-context";

export interface BrowserPanelState {
  /**
   * Which browse is expanded, by `call_id`, or `null` for none.
   *
   * An id rather than a boolean, because a turn can browse twice and both have
   * a card. "Open" is not a property of the panel, it is a property of one
   * browse - and a panel that showed "the running one" would swap page under
   * somebody reading it the moment the other browse advanced.
   */
  openCallId: string | null;
  open: (callId: string) => void;
  close: () => void;
}

/**
 * Which browse is open beside the chat or expanded.
 *
 * Only that. The browses themselves live in `use-chat`, with the delegations and
 * for the same reason - they belong to a turn, and this belongs to a person's
 * window. The selected browse stays independent of the last one that emitted an event.
 */
const browserPanelState: StateCreator<BrowserPanelState> = (set) => ({
  openCallId: null,
  open: (callId) => set({ openCallId: callId }),
  close: () => set({ openCallId: null }),
});

/** A copy of its own, for a conversation in a scope - see `ChatScope`. */
export const createBrowserPanelStore = () => createStore<BrowserPanelState>()(browserPanelState);

export const useBrowserPanelStore = scopedStore(
  create<BrowserPanelState>()(browserPanelState),
  (scope) => scope.browserPanel,
);
