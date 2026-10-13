"use client";

import { create } from "zustand";

export const MIN_PANEL_WIDTH = 360;
export const MAX_PANEL_WIDTH = 880;
export const DEFAULT_PANEL_WIDTH = 520;

/** Where an expanded browse is drawn. */
export type BrowserViewMode = "panel" | "full";

interface BrowserPanelState {
  /**
   * Which browse is expanded, by `call_id`, or `null` for none.
   *
   * An id rather than a boolean, because a turn can browse twice and both have
   * a card. "Open" is not a property of the panel, it is a property of one
   * browse - and a panel that showed "the running one" would swap page under
   * somebody reading it the moment the other browse advanced.
   */
  openCallId: string | null;
  mode: BrowserViewMode;
  /** How wide the side panel is, as somebody dragged it. Full screen ignores it. */
  width: number;
  open: (callId: string, mode: BrowserViewMode) => void;
  close: () => void;
  setWidth: (width: number) => void;
}

/**
 * Which browse is expanded, how, and how wide.
 *
 * Only that. The browses themselves live in `use-chat`, with the delegations and
 * for the same reason - they belong to a turn, and this belongs to a person's
 * window. Nothing here opens itself: a browse shows itself as a card in the
 * transcript, and expanding it is somebody's decision.
 *
 * Width is held for the session rather than persisted. `localStorage` would
 * survive a reload and also has to be wrapped in try/catch and tolerate coming
 * back empty, which is a lot of machinery for remembering a drag.
 */
export const useBrowserPanelStore = create<BrowserPanelState>((set) => ({
  openCallId: null,
  mode: "panel",
  width: DEFAULT_PANEL_WIDTH,
  open: (callId, mode) => set({ openCallId: callId, mode }),
  close: () => set({ openCallId: null }),
  setWidth: (width) =>
    set({ width: Math.min(MAX_PANEL_WIDTH, Math.max(MIN_PANEL_WIDTH, Math.round(width))) }),
}));
