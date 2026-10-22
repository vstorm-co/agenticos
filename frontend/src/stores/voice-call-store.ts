"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

interface VoiceCallPreference {
  pushToTalk: boolean;
  setPushToTalk: (on: boolean) => void;
}

/**
 * How a person talks in a call - hands-free (the default) or holding a button
 * or Space - kept in this browser like the voice glow (#54).
 */
export const useVoiceCallStore = create<VoiceCallPreference>()(
  persist((set) => ({ pushToTalk: false, setPushToTalk: (pushToTalk) => set({ pushToTalk }) }), {
    name: "voice-call-storage",
  }),
);
