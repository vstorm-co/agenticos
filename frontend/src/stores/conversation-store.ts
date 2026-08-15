"use client";

import { create } from "zustand";
import type { ConversationCost, ConversationMessage } from "@/types";

interface ConversationState {
  // UI state only. The conversations LIST is owned by React Query
  // (qk.conversations.list). This store holds the current selection, the
  // loaded messages for that selection, and the fetch/select status.
  currentConversationId: string | null;
  currentMessages: ConversationMessage[];
  /**
   * What the open thread has cost in total, as the server added it up.
   *
   * Beside the messages rather than derived from them: the transcript is paged,
   * so summing what was loaded would answer "the first page" under a label that
   * says "this conversation". Null until a transcript has been loaded, and for a
   * thread in which nothing was ever measured.
   */
  currentCost: ConversationCost | null;
  isLoading: boolean;
  error: string | null;

  setCurrentConversationId: (id: string | null) => void;
  setCurrentMessages: (messages: ConversationMessage[], cost?: ConversationCost | null) => void;
  addMessage: (message: ConversationMessage) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

const initialState = {
  currentConversationId: null,
  currentMessages: [],
  currentCost: null,
  isLoading: false,
  error: null,
};

export const useConversationStore = create<ConversationState>((set) => ({
  ...initialState,

  setCurrentConversationId: (id) => set({ currentConversationId: id }),

  // The total travels with the messages it totals. Set separately, a switch
  // between conversations would leave one thread's figure under another's
  // transcript for as long as the second fetch took.
  setCurrentMessages: (messages, cost = null) =>
    set({ currentMessages: messages, currentCost: cost }),

  addMessage: (message) =>
    set((state) => ({
      currentMessages: [...(state.currentMessages || []), message],
    })),

  setLoading: (loading) => set({ isLoading: loading }),

  setError: (error) => set({ error }),

  reset: () => set(initialState),
}));
