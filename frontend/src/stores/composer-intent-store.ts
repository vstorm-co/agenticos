"use client";

import { create } from "zustand";

/** How a shortcut outside the console asks the chat to start: a call, or dictation. */
export type ComposerIntent = "call" | "dictate";

interface ComposerIntentState {
  /** What the chat should start once its agent is ready, or null. */
  intent: ComposerIntent | null;
  request: (intent: ComposerIntent) => void;
  clear: () => void;
}

/**
 * A phone shortcut's "Voice call" or "Dictate" (#2097), on its way to `/chat`.
 *
 * The bridge that reads the shortcut navigates to the chat and leaves the
 * intent here; the chat acts on it once the selected agent's readiness has
 * loaded, through the same handlers its buttons use, and clears it - started,
 * or refused with the button's own reason in view.
 */
export const useComposerIntentStore = create<ComposerIntentState>((set) => ({
  intent: null,
  request: (intent) => set({ intent }),
  clear: () => set({ intent: null }),
}));
