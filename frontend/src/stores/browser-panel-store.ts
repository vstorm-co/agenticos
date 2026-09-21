"use client";

import { create } from "zustand";

interface BrowserPanelState {
  isOpen: boolean;
  /**
   * Browses the person closed the panel on, so it stays closed for them.
   *
   * The panel opens itself when a browse starts, which is the point of a live
   * preview - but a person who closed it did not close one frame, they closed
   * this browse, and re-opening on the next step would make the control useless
   * at exactly the moment it is being used. Keyed by `call_id`, so the *next*
   * browse opens normally.
   */
  dismissed: string[];
  /** Open for this browse, unless it is one the person already closed. */
  openFor: (callId: string) => void;
  close: (callId: string | null) => void;
}

export const useBrowserPanelStore = create<BrowserPanelState>((set) => ({
  isOpen: false,
  dismissed: [],
  openFor: (callId) =>
    set((state) => (state.dismissed.includes(callId) ? state : { ...state, isOpen: true })),
  close: (callId) =>
    set((state) => ({
      isOpen: false,
      dismissed:
        callId && !state.dismissed.includes(callId)
          ? [...state.dismissed, callId]
          : state.dismissed,
    })),
}));
