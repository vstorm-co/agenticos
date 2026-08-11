"use client";

import { create } from "zustand";

import type { FlowId } from "@/lib/onboarding/flows";

/**
 * How the tour was opened, and where it has reached.
 *
 * `"tour"` is the first-run walkthrough: every page in order, and closing it
 * records that onboarding is done. `"page"` is the per-page "?" replay: only the
 * current page's highlights, and closing it records nothing — it is contextual
 * help a returning user asked for, not the first run. `"flow"` is a Phase-2
 * interactive walkthrough where the reader actually creates something; it is not
 * driven by driver.js (its overlay would cover the create dialog) but by the
 * coach in `components/onboarding`, and `flowId` says which one is running.
 *
 * UI state only, per the store rule. Whether a user has *finished* onboarding is
 * server truth (`users.onboarding_completed_at`, read through the auth store and
 * written through `PATCH /users/me`), never kept here: a persisted browser flag
 * would let the tour reappear on the next device, and a cleared one would lose a
 * dismissal a colleague made on a shared machine. Nothing in this store survives
 * a reload, which is the point.
 */
export type OnboardingMode = "tour" | "page" | "flow";

interface OnboardingState {
  isOpen: boolean;
  index: number;
  mode: OnboardingMode;
  /** Which interactive flow is running, when `mode === "flow"`; `null` otherwise. */
  flowId: FlowId | null;
  /**
   * The flow the reader is being *offered*, if any — the "Create X? [Yes] [Not
   * now]" prompt. Independent of `isOpen`: an offer can sit over a closed
   * walkthrough (the "?" walk has ended) and only becomes a running flow if
   * accepted. `null` means no prompt is showing.
   */
  offer: FlowId | null;
  /** The first-run walkthrough, from the top — the auto-start and a full replay. */
  openTour: () => void;
  /** The current page's highlights only — the header "?" button. */
  openPage: () => void;
  /** Start an interactive flow, clearing any offer that led here. */
  openFlow: (flowId: FlowId) => void;
  /** Show the "Create X?" prompt for a flow, without starting it. */
  openOffer: (flowId: FlowId) => void;
  /** Dismiss the prompt — the reader declined, and nothing is recorded. */
  dismissOffer: () => void;
  close: () => void;
  setIndex: (index: number) => void;
}

export const useOnboardingStore = create<OnboardingState>((set) => ({
  isOpen: false,
  index: 0,
  mode: "tour",
  flowId: null,
  offer: null,
  openTour: () => set({ isOpen: true, index: 0, mode: "tour", flowId: null }),
  openPage: () => set({ isOpen: true, index: 0, mode: "page", flowId: null }),
  openFlow: (flowId) => set({ isOpen: true, index: 0, mode: "flow", flowId, offer: null }),
  openOffer: (flowId) => set({ offer: flowId }),
  dismissOffer: () => set({ offer: null }),
  close: () => set({ isOpen: false }),
  setIndex: (index) => set({ index }),
}));
