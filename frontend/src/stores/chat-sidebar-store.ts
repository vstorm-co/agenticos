"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

interface ChatSidebarState {
  isOpen: boolean;
  open: () => void;
  close: () => void;
  toggle: () => void;
}

export const useChatSidebarStore = create<ChatSidebarState>((set) => ({
  isOpen: false,
  open: () => set({ isOpen: true }),
  close: () => set({ isOpen: false }),
  toggle: () => set((state) => ({ isOpen: !state.isOpen })),
}));

interface ChatBandsState {
  /** The bands of the conversation list folded to their heading, by key. */
  collapsed: string[];
  toggle: (band: string) => void;
}

/**
 * Which bands of the conversation list - Unread, Favourites, Today and the rest
 * - this reader has folded. Kept in the browser: it is how one person likes the
 * list laid out on one screen, not something another device or anybody else
 * needs to know.
 */
export const useChatBandsStore = create<ChatBandsState>()(
  persist(
    (set) => ({
      collapsed: [],
      toggle: (band) =>
        set((state) => ({
          collapsed: state.collapsed.includes(band)
            ? state.collapsed.filter((key) => key !== band)
            : [...state.collapsed, band],
        })),
    }),
    { name: "chat-collapsed-bands" },
  ),
);
