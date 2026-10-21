"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

/** How the composer's glow answers a voice: colourful, a quiet edge, or not at all. */
export type VoiceGlowStyle = "vivid" | "subtle" | "off";

interface VoiceGlowState {
  style: VoiceGlowStyle;
  setStyle: (style: VoiceGlowStyle) => void;
}

/**
 * How loudly the composer reacts to a voice - a person's taste, kept in this
 * browser like the theme. Subtle by default: the colourful glow read as a
 * light show on a console that is otherwise neutral.
 */
export const useVoiceGlowStore = create<VoiceGlowState>()(
  persist(
    (set) => ({
      style: "subtle",
      setStyle: (style) => set({ style }),
    }),
    { name: "voice-glow-storage" },
  ),
);
