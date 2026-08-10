"use client";

import { create } from "zustand";

/**
 * Whether the walkthrough is open, and which step is showing.
 *
 * UI state only, per the store rule. Whether a user has *finished* onboarding is
 * server truth (`users.onboarding_completed_at`, read through the auth store and
 * written through `PATCH /users/me`), never kept here: a persisted browser flag
 * would let the tour reappear on the next device, and a cleared one would lose a
 * dismissal a colleague made on a shared machine. Nothing in this store survives
 * a reload, which is the point.
 */
interface OnboardingState {
  isOpen: boolean;
  index: number;
  /** Open at the first step — both the first-run auto-start and the restart control. */
  restart: () => void;
  close: () => void;
  setIndex: (index: number) => void;
}

export const useOnboardingStore = create<OnboardingState>((set) => ({
  isOpen: false,
  index: 0,
  restart: () => set({ isOpen: true, index: 0 }),
  close: () => set({ isOpen: false }),
  setIndex: (index) => set({ index }),
}));
