"use client";

import { create } from "zustand";

import type { IncomingFiles } from "@/components/chat/chat-input";

/** How a shortcut outside the console asks the chat to start: a call, or dictation. */
export type ComposerIntent = "call" | "dictate";

interface ComposerIntentState {
  /** What the chat should start once its agent is ready, or null. */
  intent: ComposerIntent | null;
  request: (intent: ComposerIntent) => void;
  clear: () => void;
  /** What another app shared with the phone app, for the chat's next message. */
  shared: IncomingFiles | null;
  share: (shared: IncomingFiles) => void;
  clearShared: () => void;
}

/**
 * What the phone app hands the chat from outside the console (#2097): a
 * shortcut's "Voice call" or "Dictate", or what another app shared.
 *
 * The bridge that reads it navigates to the chat and leaves it here. The chat
 * starts a call or dictation once the selected agent's readiness has loaded,
 * through the handlers its buttons use - started, or refused with the button's
 * own reason in view - and takes what was shared into the composer.
 */
export const useComposerIntentStore = create<ComposerIntentState>((set) => ({
  intent: null,
  request: (intent) => set({ intent }),
  clear: () => set({ intent: null }),
  shared: null,
  share: (shared) => set({ shared }),
  clearShared: () => set({ shared: null }),
}));
