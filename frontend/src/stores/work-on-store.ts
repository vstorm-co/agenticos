"use client";

import { readChatControlPreferences, saveChatControlPreferences } from "./chat-controls-store";
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
 * folder keeps working there. New chats inherit account and organization defaults.
 * `draft` is the choice made before a new chat has an id; it moves under that id when the
 * server files the conversation. Only paths and modes are kept - what the person
 * granted is the desktop app's to check on every operation, not this store's.
 */
const browserKey = (conversationId: string) =>
  `${useAuthStore.getState().user?.id ?? "-"}:${useOrgStore.getState().activeOrgId ?? "-"}:${conversationId}`;

interface WorkOnState {
  computerByConversation: Record<string, boolean>;
  draftComputer: boolean | undefined;
  computerFor: (conversationId: string | null) => boolean;
  setComputer: (conversationId: string | null, local: boolean) => void;
  browserByConversation: Record<string, boolean>;
  draftBrowser: boolean | undefined;
  browserFor: (conversationId: string | null) => boolean;
  setBrowser: (conversationId: string | null, local: boolean) => void;
  byConversation: Record<string, LocalTarget | null>;
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
      computerByConversation: {},
      draftComputer: undefined,
      computerFor: (conversationId) =>
        (conversationId === null
          ? get().draftComputer
          : get().computerByConversation[browserKey(conversationId)]) ??
        get().targetFor(conversationId)?.computer ??
        readChatControlPreferences().computer,
      setComputer: (conversationId, local) => {
        saveChatControlPreferences({ computer: local });
        const target = get().targetFor(conversationId);
        if (target !== null) get().set(conversationId, { ...target, computer: local });
        if (conversationId === null) set({ draftComputer: local });
        else
          set({
            computerByConversation: {
              ...get().computerByConversation,
              [browserKey(conversationId)]: local,
            },
          });
      },
      browserByConversation: {},
      draftBrowser: undefined,
      browserFor: (conversationId) =>
        (conversationId === null
          ? get().draftBrowser
          : get().browserByConversation[browserKey(conversationId)]) ??
        get().targetFor(conversationId)?.browser ??
        readChatControlPreferences().browser,
      setBrowser: (conversationId, local) => {
        saveChatControlPreferences({ browser: local });
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
      resetDraft: () =>
        set({
          draft: null,
          draftProjectKey: null,
          draftBrowser: undefined,
          draftComputer: undefined,
        }),
      targetFor: (conversationId) => {
        if (conversationId === null)
          return get().draftProjectKey !== null
            ? get().draft
            : (get().draft ?? readChatControlPreferences().localTarget);
        return Object.hasOwn(get().byConversation, conversationId)
          ? (get().byConversation[conversationId] ?? null)
          : readChatControlPreferences().localTarget;
      },
      set: (conversationId, target) => {
        // Whole-computer consent belongs to one conversation and is never inherited.
        saveChatControlPreferences({ localTarget: target?.computer_grant ? null : target });
        if (conversationId === null) {
          set({ draft: target });
          return;
        }
        set({ byConversation: { ...get().byConversation, [conversationId]: target } });
      },
      adopt: (conversationId) => {
        const state = get();
        if (Object.hasOwn(state.byConversation, conversationId)) return;
        const key = browserKey(conversationId);
        const target = state.targetFor(null);
        set({
          draft: null,
          draftProjectKey: null,
          draftComputer: undefined,
          draftBrowser: undefined,
          browserByConversation: Object.hasOwn(state.browserByConversation, key)
            ? state.browserByConversation
            : { ...state.browserByConversation, [key]: state.browserFor(null) },
          computerByConversation: Object.hasOwn(state.computerByConversation, key)
            ? state.computerByConversation
            : { ...state.computerByConversation, [key]: state.computerFor(null) },
          byConversation: { ...state.byConversation, [conversationId]: target },
        });
      },
    }),
    {
      name: "work-on",
      version: 1,
      partialize: ({ byConversation, browserByConversation, computerByConversation }) => ({
        byConversation,
        browserByConversation,
        computerByConversation,
      }),
    },
  ),
);
