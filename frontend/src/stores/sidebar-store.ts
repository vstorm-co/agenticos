"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

interface SidebarState {
  /** The mobile slide-over. Ephemeral: nothing about it is worth remembering. */
  isOpen: boolean;
  open: () => void;
  close: () => void;
  toggle: () => void;
  /**
   * Whether the desktop column is collapsed to an icon rail.
   *
   * Persisted, and that is the whole point: somebody who wants the width back
   * for a transcript wants it back tomorrow too, and a preference that resets
   * on every page load is one nobody sets twice. It is a property of the
   * browser rather than of the account, which is why it lives here and in
   * `localStorage` rather than in the profile - and why `resetSessionState`
   * deliberately leaves it alone when somebody signs out.
   */
  isCollapsed: boolean;
  toggleCollapsed: () => void;
  /**
   * The folding groups somebody opened, by label key. Persisted for the same
   * reason the collapse is: somebody who keeps Connections open wants it open
   * tomorrow too.
   */
  openGroups: string[];
  toggleGroup: (key: string) => void;
}

export const useSidebarStore = create<SidebarState>()(
  persist(
    (set) => ({
      isOpen: false,
      open: () => set({ isOpen: true }),
      close: () => set({ isOpen: false }),
      toggle: () => set((state) => ({ isOpen: !state.isOpen })),
      isCollapsed: false,
      toggleCollapsed: () => set((state) => ({ isCollapsed: !state.isCollapsed })),
      openGroups: [],
      toggleGroup: (key) =>
        set((state) => ({
          openGroups: state.openGroups.includes(key)
            ? state.openGroups.filter((open) => open !== key)
            : [...state.openGroups, key],
        })),
    }),
    {
      name: "agenticos.sidebar",
      // Not `isOpen`: that is the phone's slide-over, and restoring it would
      // open a drawer over the page somebody just loaded.
      partialize: (state) => ({ isCollapsed: state.isCollapsed, openGroups: state.openGroups }),
    },
  ),
);
