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
  /** Bands this reader folded by hand, by key. */
  folded: string[];
  /** Bands this reader opened by hand - a default fold they undid. */
  opened: string[];
  /** Record the reader's choice for `band`, from how it is drawn right now. */
  toggle: (band: string, foldedNow: boolean) => void;
}

/**
 * The bands that fold by default - but only on a long list, and never the
 * newest band on it. What is a week or more old is there to be found rather
 * than read past, which matters when there is a lot of it; on a short list the
 * fold hid the only threads there were, and a person with nothing from the last
 * two days opened Chats onto two headings and no conversation.
 */
export const DEFAULT_COLLAPSED_BANDS = ["week", "month", "older"];

/** How many threads make a list long enough for the older bands to fold. */
export const LONG_LIST = 20;

/**
 * Which bands of the conversation list - Unread, Favourites, Today and the rest
 * - this reader has folded or opened by hand. Kept in the browser: it is how one
 * person likes the list laid out on one screen, not something another device or
 * anybody else needs to know. A band nobody chose for follows the default.
 *
 * Version 2 starts everybody from the default once: version 1 stored the
 * default folds as if they were the reader's, so they could not give way on a
 * short list.
 */
export const useChatBandsStore = create<ChatBandsState>()(
  persist(
    (set) => ({
      folded: [],
      opened: [],
      toggle: (band, foldedNow) =>
        set((state) => ({
          folded: foldedNow
            ? state.folded.filter((key) => key !== band)
            : [...state.folded.filter((key) => key !== band), band],
          opened: foldedNow
            ? [...state.opened.filter((key) => key !== band), band]
            : state.opened.filter((key) => key !== band),
        })),
    }),
    {
      name: "chat-collapsed-bands",
      version: 2,
      migrate: () => ({ folded: [], opened: [] }),
    },
  ),
);
