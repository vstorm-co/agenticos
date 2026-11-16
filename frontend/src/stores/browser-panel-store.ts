"use client";

import { create, createStore, type StateCreator } from "zustand";

import { scopedStore } from "./chat-scope-context";

export type WorkspaceSurface = "browser" | "computer" | "files" | "settings";
export type BrowseSurface = Extract<WorkspaceSurface, "browser" | "computer">;

export interface BrowserPanelState {
  /** The person's choice, including a pane opened before any tool has run. */
  surface: WorkspaceSurface | null;
  /**
   * An explicitly selected visit, or null to follow the latest view in the chosen pane.
   *
   * An id rather than a boolean, because a turn can browse twice and both have
   * a card. "Open" is not a property of the panel, it is a property of one
   * browse. Explicitly opening a historical visit must not jump to another one.
   */
  openCallId: string | null;
  open: (callId: string, surface?: BrowseSurface) => void;
  openSurface: (surface: WorkspaceSurface) => void;
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
  surface: null,
  openCallId: null,
  open: (callId, surface = "browser") => set({ surface, openCallId: callId }),
  openSurface: (surface) => set({ surface, openCallId: null }),
  close: () => set({ surface: null, openCallId: null }),
});

/** A copy of its own, for a conversation in a scope - see `ChatScope`. */
export const createBrowserPanelStore = () => createStore<BrowserPanelState>()(browserPanelState);

export const useBrowserPanelStore = scopedStore(
  create<BrowserPanelState>()(browserPanelState),
  (scope) => scope.browserPanel,
);
