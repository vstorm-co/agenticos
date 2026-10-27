"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";
import { useAuthStore } from "./auth-store";
import { useOrgStore } from "./org-store";

import type { LocalTarget } from "@/lib/desktop/commands";

export type { LocalTarget };

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
const browserKey = (conversationId: string) =>
  `${useAuthStore.getState().user?.id ?? "-"}:${useOrgStore.getState().activeOrgId ?? "-"}:${conversationId}`;

interface WorkOnState {
  browserByConversation: Record<string, boolean>;
  draftBrowser: boolean | undefined;
  browserFor: (conversationId: string | null) => boolean;
  setBrowser: (conversationId: string | null, local: boolean) => void;
  byConversation: Record<string, LocalTarget>;
  draft: LocalTarget | null;
  draftProjectKey: string | null;
  /** Apply a project default once; subsequent edits belong to this draft. */
  applyProject: (key: string | null, target: LocalTarget | null) => void;
  resetDraft: () => void;
  /** The target for a conversation, or the draft for one not filed yet. */
  targetFor: (conversationId: string | null) => LocalTarget | null;
  set: (conversationId: string | null, target: LocalTarget | null) => void;
  /** File the draft under the id the server just gave the new chat. */
  adopt: (conversationId: string) => void;
}

export const useWorkOnStore = create<WorkOnState>()(
  persist(
    (set, get) => ({
      browserByConversation: {},
      draftBrowser: undefined,
      browserFor: (conversationId) =>
        (conversationId === null
          ? get().draftBrowser
          : get().browserByConversation[browserKey(conversationId)]) ??
        get().targetFor(conversationId)?.browser ??
        false,
      setBrowser: (conversationId, local) => {
        const target = get().targetFor(conversationId);
        if (target !== null) get().set(conversationId, { ...target, browser: local });
        if (conversationId === null) set({ draftBrowser: local });
        else
          set({
            browserByConversation: {
              ...get().browserByConversation,
              [browserKey(conversationId)]: local,
            },
          });
      },
      byConversation: {},
      draft: null,
      draftProjectKey: null,
      applyProject: (key, target) => {
        if (key !== get().draftProjectKey) set({ draftProjectKey: key, draft: target });
      },
      resetDraft: () => set({ draft: null, draftProjectKey: null, draftBrowser: undefined }),
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
        const { draft, byConversation, draftBrowser, browserByConversation } = get();
        if (draftBrowser !== undefined)
          set({
            draftBrowser: undefined,
            browserByConversation: {
              ...browserByConversation,
              [browserKey(conversationId)]: draftBrowser,
            },
          });
        if (draft === null || conversationId in byConversation) return;
        set({
          draft: null,
          draftProjectKey: null,
          byConversation: { ...byConversation, [conversationId]: draft },
        });
      },
    }),
    {
      name: "work-on",
      version: 1,
      partialize: ({ byConversation, browserByConversation }) => ({
        byConversation,
        browserByConversation,
      }),
    },
  ),
);
