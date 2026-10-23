"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { LocalMode } from "@/lib/desktop/commands";

/** A folder on the person's own computer, and how far a run may reach in it. */
export interface LocalTarget {
  folder: string;
  mode: LocalMode;
}

/**
 * Where each conversation's runs work: the agent's cloud sandbox, or a folder on
 * this computer (#2305).
 *
 * Remembered per conversation, so reopening a chat that worked in a project
 * folder keeps working there, and a new chat starts in the cloud. `draft` is the
 * choice made before a new chat has an id; it moves under that id when the
 * server files the conversation. Only paths and modes are kept - what the person
 * granted is the desktop app's to check on every operation, not this store's.
 */
interface WorkOnState {
  byConversation: Record<string, LocalTarget>;
  draft: LocalTarget | null;
  /** The target for a conversation, or the draft for one not filed yet. */
  targetFor: (conversationId: string | null) => LocalTarget | null;
  set: (conversationId: string | null, target: LocalTarget | null) => void;
  /** File the draft under the id the server just gave the new chat. */
  adopt: (conversationId: string) => void;
}

export const useWorkOnStore = create<WorkOnState>()(
  persist(
    (set, get) => ({
      byConversation: {},
      draft: null,
      targetFor: (conversationId) =>
        conversationId === null ? get().draft : (get().byConversation[conversationId] ?? null),
      set: (conversationId, target) => {
        if (conversationId === null) {
          set({ draft: target });
          return;
        }
        const { [conversationId]: _previous, ...rest } = get().byConversation;
        set({ byConversation: target === null ? rest : { ...rest, [conversationId]: target } });
      },
      adopt: (conversationId) => {
        const { draft, byConversation } = get();
        if (draft === null || conversationId in byConversation) return;
        set({ draft: null, byConversation: { ...byConversation, [conversationId]: draft } });
      },
    }),
    { name: "work-on", version: 1, partialize: ({ byConversation }) => ({ byConversation }) },
  ),
);
