"use client";

import { create } from "zustand";

interface LiveFeedState {
  /** Whether this tab's `/ws/events` socket is open right now. */
  connected: boolean;
  setConnected: (connected: boolean) => void;
}

/**
 * Whether the live-update socket is carrying changes to this tab.
 *
 * A list that polls to notice a change can ask far less often while the socket
 * is up, because the change arrives as an event and invalidates the list. It
 * still asks now and then: not every change is announced - a run the stale-run
 * sweep ends, for one - and the socket being open is not proof that nothing was
 * missed while it reconnected.
 */
export const useLiveFeedStore = create<LiveFeedState>()((set) => ({
  connected: false,
  setConnected: (connected) => set({ connected }),
}));
