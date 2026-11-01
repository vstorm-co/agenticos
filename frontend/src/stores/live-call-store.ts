"use client";

import { create } from "zustand";

/** The voice call this page holds, as the phone app shows it outside itself. */
export interface LiveCall {
  callId: string;
  /** The call's run, which the runs list would otherwise show as a second activity. */
  runId: string | null;
  agentId: string;
  conversationId: string | null;
  /** Milliseconds since the epoch, for the clock the phone counts up. */
  startedAt: number;
  /** The agent asked something on the call and waits for the answer. */
  asking: boolean;
}

interface LiveCallState {
  call: LiveCall | null;
  set: (call: LiveCall | null) => void;
}

/**
 * The call in progress, published by the chat that holds it (#2305).
 *
 * A call is a socket owned by the chat page, so nothing else can ask the server
 * about it; the phone app's live activity reads it from here instead. Only the
 * page that holds the call writes it, and it clears it when the call ends.
 */
export const useLiveCallStore = create<LiveCallState>()((set) => ({
  call: null,
  set: (call) => set({ call }),
}));
