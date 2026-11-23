"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

import {
  DEFAULT_MOTION_PREFERENCE,
  isMotionPreference,
  MOTION_STORAGE_KEY,
  type MotionPreference,
} from "@/lib/motion-preference";

export type { MotionPreference } from "@/lib/motion-preference";

interface MotionState {
  motion: MotionPreference;
  setMotion: (motion: MotionPreference) => void;
}

/**
 * How much the console moves for this person - kept in this browser like the
 * theme. `"full"` by default; `"system"` follows the operating system and
 * `"reduce"` asks for less without it. Read through `useReducedMotion` or
 * `prefersReducedMotion`, never directly: what counts is the resolved answer.
 */
export const useMotionStore = create<MotionState>()(
  persist(
    (set) => ({
      motion: DEFAULT_MOTION_PREFERENCE,
      setMotion: (motion) => set({ motion }),
    }),
    {
      name: MOTION_STORAGE_KEY,
      merge: (persisted, current) => ({
        ...current,
        motion:
          persisted &&
          typeof persisted === "object" &&
          "motion" in persisted &&
          isMotionPreference(persisted.motion)
            ? persisted.motion
            : DEFAULT_MOTION_PREFERENCE,
      }),
    },
  ),
);
