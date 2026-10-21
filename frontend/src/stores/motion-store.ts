"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

import { MOTION_STORAGE_KEY, type MotionPreference } from "@/lib/motion-preference";

export type { MotionPreference } from "@/lib/motion-preference";

interface MotionState {
  motion: MotionPreference;
  setMotion: (motion: MotionPreference) => void;
}

/**
 * How much the console moves for this person - kept in this browser like the
 * theme. `"system"` by default, so nobody who set reduced motion at the
 * operating system has to say it twice; `"full"` overrides that setting and
 * `"reduce"` asks for less without it. Read through `useReducedMotion` or
 * `prefersReducedMotion`, never directly: what counts is the resolved answer.
 */
export const useMotionStore = create<MotionState>()(
  persist(
    (set) => ({
      motion: "system",
      setMotion: (motion) => set({ motion }),
    }),
    { name: MOTION_STORAGE_KEY },
  ),
);
