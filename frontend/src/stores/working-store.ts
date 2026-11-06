"use client";

import { create } from "zustand";

export interface WorkingState {
  /** When this tab's turn began, by the conversation it is running in. */
  since: Readonly<Record<string, string>>;
  /** Completed locally: ignore list responses that still contain the previous run. */
  finishedAt: Readonly<Record<string, string>>;
  finishedRuns: Readonly<Record<string, Readonly<Record<string, true>>>>;
  waiting: Readonly<Record<string, "awaiting_answer" | "awaiting_approval">>;
  setWaiting: (
    conversationId: string,
    status: "awaiting_answer" | "awaiting_approval" | null,
  ) => void;
  /** Threads whose turn this tab let go to the server - see `handOff`. */
  handedOff: Readonly<Record<string, true>>;
  start: (conversationId: string, since: string) => void;
  /** This tab's turn is over. A handed-off thread keeps its mark until `settle`. */
  stop: (conversationId: string) => void;
  /** A terminal socket frame confirmed this turn ended, rather than merely detached. */
  finish: (conversationId: string, runId?: string) => void;
  /**
   * The person opened another thread while this one was answering, and the turn
   * goes on on the server. Its mark stays: the listing may not have seen the run
   * yet - the very gap this store covers - and the row would go idle mid-answer.
   */
  handOff: (conversationId: string) => void;
  /** The listing speaks for this thread now, or never will: drop its mark. */
  settle: (conversationId: string) => void;
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
  finishedAt: {},
  finishedRuns: {},
  waiting: {},
  setWaiting: (conversationId, status) =>
    set((state) => {
      const { [conversationId]: _previous, ...waiting } = state.waiting;
      return { waiting: status === null ? waiting : { ...waiting, [conversationId]: status } };
    }),
  handedOff: {},
  start: (conversationId, since) =>
    set((state) => ({ since: { ...state.since, [conversationId]: since } })),
  stop: (conversationId) =>
    set((state) => {
      if (!(conversationId in state.since) || conversationId in state.handedOff) return state;
      const { [conversationId]: _stopped, ...rest } = state.since;
      return { since: rest };
    }),
  finish: (conversationId, runId) =>
    set((state) => {
      const { [conversationId]: _since, ...since } = state.since;
      const { [conversationId]: _handed, ...handedOff } = state.handedOff;
      const { [conversationId]: _waiting, ...waiting } = state.waiting;
      return {
        since,
        handedOff,
        waiting,
        finishedAt: { ...state.finishedAt, [conversationId]: new Date().toISOString() },
        finishedRuns: runId
          ? {
              ...state.finishedRuns,
              [conversationId]: { ...state.finishedRuns[conversationId], [runId]: true },
            }
          : state.finishedRuns,
      };
    }),
  handOff: (conversationId) =>
    set((state) =>
      conversationId in state.since
        ? { handedOff: { ...state.handedOff, [conversationId]: true } }
        : state,
    ),
  settle: (conversationId) =>
    set((state) => {
      if (!(conversationId in state.since) && !(conversationId in state.handedOff)) return state;
      const { [conversationId]: _since, ...since } = state.since;
      const { [conversationId]: _handed, ...handedOff } = state.handedOff;
      return { since, handedOff };
    }),
  reset: () => set({ since: {}, finishedAt: {}, finishedRuns: {}, waiting: {}, handedOff: {} }),
}));
