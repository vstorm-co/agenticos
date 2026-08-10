"use client";

import { create } from "zustand";

/**
 * How the tour was opened, and where it has reached.
 *
 * `"tour"` is the first-run walkthrough: every page in order, and closing it
 * records that onboarding is done. `"page"` is the per-page "?" replay: only the
 * current page's highlights, and closing it records nothing — it is contextual
 * help a returning user asked for, not the first run.
 *
 * UI state only, per the store rule. Whether a user has *finished* onboarding is
 * server truth (`users.onboarding_completed_at`, read through the auth store and
 * written through `PATCH /users/me`), never kept here: a persisted browser flag
 * would let the tour reappear on the next device, and a cleared one would lose a
 * dismissal a colleague made on a shared machine. Nothing in this store survives
 * a reload, which is the point.
 */
export type OnboardingMode = "tour" | "page";

interface OnboardingState {
  isOpen: boolean;
  index: number;
  mode: OnboardingMode;
  /** The first-run walkthrough, from the top — the auto-start and a full replay. */
  openTour: () => void;
  /** The current page's highlights only — the header "?" button. */
  openPage: () => void;
  close: () => void;
  setIndex: (index: number) => void;
}

export const useOnboardingStore = create<OnboardingState>((set) => ({
  isOpen: false,
  index: 0,
  mode: "tour",
  openTour: () => set({ isOpen: true, index: 0, mode: "tour" }),
  openPage: () => set({ isOpen: true, index: 0, mode: "page" }),
  close: () => set({ isOpen: false }),
  setIndex: (index) => set({ index }),
}));
