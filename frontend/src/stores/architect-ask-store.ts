"use client";

import { create } from "zustand";

interface ArchitectAsk {
  /** Increments with every ask, so the same words asked twice are two asks. */
  id: number;
  text: string;
  /** Written into the Architect's message box for the person to send, rather than sent. */
  draft: boolean;
}

interface ArchitectAskState {
  /** The last thing somewhere else in the console asked the Architect, or null. */
  request: ArchitectAsk | null;
  ask: (text: string, options?: { draft?: boolean }) => void;
  /** Taken by the widget once asked, so a widget mounted later does not ask it again. */
  answered: (id: number) => void;
}

// Outside the state: an ask taken out of the store must not hand its id to the next one.
let asks = 0;

/**
 * Something outside the Architect's window asking it a question (#2301) - "Make
 * an agent of this" under a chat message. The widget opens and sends it; the
 * window's own conversation is the Architect's, so nothing here holds a reply.
 */
export const useArchitectAskStore = create<ArchitectAskState>((set) => ({
  request: null,
  ask: (text, options) => set({ request: { id: ++asks, text, draft: options?.draft ?? false } }),
  answered: (id) => set((state) => (state.request?.id === id ? { request: null } : state)),
}));
