"use client";

import { create, createStore, type StateCreator } from "zustand";

import { scopedStore } from "./chat-scope-context";
import type { ConversationCost, ConversationMessage } from "@/types";

export interface ConversationState {
  // UI state only. The conversations LIST is owned by React Query
  // (qk.conversations.list). This store holds the current selection, the
  // loaded messages for that selection, and the fetch/select status.
  currentConversationId: string | null;
  currentMessages: ConversationMessage[];
  hasEarlierMessages: boolean;
  /**
   * What the open thread has cost in total, as the server added it up.
   *
   * Beside the messages rather than derived from them: the transcript is paged,
   * so summing what was loaded would answer "the first page" under a label that
   * says "this conversation". Null until a transcript has been loaded, and for a
   * thread in which nothing was ever measured.
   */
  currentCost: ConversationCost | null;
  /**
   * The project the next new conversation starts in. Read only while there is no
   * conversation yet: a chat is in the project it was started in, and stays there.
   */
  pendingProjectId: string | null;
  isLoading: boolean;
  error: string | null;

  setCurrentConversationId: (id: string | null) => void;
  setCurrentMessages: (
    messages: ConversationMessage[],
    cost?: ConversationCost | null,
    hasEarlier?: boolean,
  ) => void;
  /**
   * Replace the thread's total on its own, without touching the transcript.
   *
   * A turn adds to the bill, and the total was read when the transcript loaded -
   * so without this the figure under the composer is a conversation ago by the
   * second message. It is re-read from the server rather than added to here:
   * money is the one number a client must not compute a second way, and a run
   * that parked and resumed reports its cost cumulatively, so the obvious
   * arithmetic double-counts exactly the turn somebody had to approve.
   */
  setCurrentCost: (cost: ConversationCost | null) => void;
  setPendingProjectId: (projectId: string | null) => void;
  addMessage: (message: ConversationMessage) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

const initialState = {
  currentConversationId: null,
  currentMessages: [],
  hasEarlierMessages: false,
  currentCost: null,
  pendingProjectId: null,
  isLoading: false,
  error: null,
};

const conversationState: StateCreator<ConversationState> = (set) => ({
  ...initialState,

  setCurrentConversationId: (id) => set({ currentConversationId: id }),

  // The total travels with the messages it totals. Set separately, a switch
  // between conversations would leave one thread's figure under another's
  // transcript for as long as the second fetch took.
  setCurrentMessages: (messages, cost = null, hasEarlier = false) =>
    set({ currentMessages: messages, currentCost: cost, hasEarlierMessages: hasEarlier }),

  setCurrentCost: (cost) => set({ currentCost: cost }),

  setPendingProjectId: (projectId) => set({ pendingProjectId: projectId }),

  addMessage: (message) =>
    set((state) => ({
      currentMessages: [...(state.currentMessages || []), message],
    })),

  setLoading: (loading) => set({ isLoading: loading }),

  setError: (error) => set({ error }),

  reset: () => set(initialState),
});

/** A copy of its own, for a conversation in a scope - see `ChatScope`. */
export const createConversationStore = () => createStore<ConversationState>()(conversationState);

export const useConversationStore = scopedStore(
  create<ConversationState>()(conversationState),
  (scope) => scope.conversation,
);
