"use client";

import { create } from "zustand";

export interface WorkingState {
  /** When this tab's turn began, by the conversation it is running in. */
  since: Readonly<Record<string, string>>;
  start: (conversationId: string, since: string) => void;
  stop: (conversationId: string) => void;
  reset: () => void;
}

/**
 * The conversations this tab is waiting on an answer in.
 *
 * The list of conversations says a run is at work from the server's
 * `running_since`, which reaches it through the live-update socket - and a turn
 * of a few seconds could start and end before that socket said anything, or
 * while it was reconnecting, leaving the thread somebody had just asked in
 * looking idle. The tab that sent the question knows without asking anybody.
 *
 * Not scoped to a chat: the Architect's window and the chat page both run turns,
 * and the list shows every thread, so both write here, each to its own key.
 */
export const useWorkingStore = create<WorkingState>()((set) => ({
  since: {},
  start: (conversationId, since) =>
    set((state) => ({ since: { ...state.since, [conversationId]: since } })),
  stop: (conversationId) =>
    set((state) => {
      if (!(conversationId in state.since)) return state;
      const { [conversationId]: _stopped, ...rest } = state.since;
      return { since: rest };
    }),
  reset: () => set({ since: {} }),
}));
