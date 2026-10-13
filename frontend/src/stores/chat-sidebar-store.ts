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
 * Folded until opened: what is a week or more old is there to be found, not
 * read past on the way to today's threads, so a list starts with Today and
 * Yesterday open and the older bands at their headings.
 */
export const DEFAULT_COLLAPSED_BANDS = ["week", "month", "older"];

/**
 * Which bands of the conversation list - Unread, Favourites, Today and the rest
 * - this reader has folded. Kept in the browser: it is how one person likes the
 * list laid out on one screen, not something another device or anybody else
 * needs to know.
 *
 * Version 1 starts everybody from the default once: before it, every band
 * started open, and a list somebody had folded by hand kept Yesterday shut
 * above an open week.
 */
export const useChatBandsStore = create<ChatBandsState>()(
  persist(
    (set) => ({
      collapsed: DEFAULT_COLLAPSED_BANDS,
      toggle: (band) =>
        set((state) => ({
          collapsed: state.collapsed.includes(band)
            ? state.collapsed.filter((key) => key !== band)
            : [...state.collapsed, band],
        })),
    }),
    {
      name: "chat-collapsed-bands",
      version: 1,
      migrate: () => ({ collapsed: DEFAULT_COLLAPSED_BANDS }),
    },
  ),
);
