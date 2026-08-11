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

/**
 * A reader's answer at a fork in a flow — the "no knowledge base yet, create
 * one?" question. `"yes"` opens the detour that guides the creation and the
 * round-trip back; `"skip"` steps over it. Kept per running flow and cleared
 * when the next one starts, because it is a decision inside a flow, not state
 * that should outlive it.
 */
export type ChoiceValue = "yes" | "skip";

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
  /**
   * The forks the reader has answered in the running flow, keyed by the
   * question step's id. A detour step runs only when its `requires` question is
   * answered `"yes"` here, so recording an answer is what widens the step list
   * to include the guided creation. Emptied at every flow start.
   */
  choices: Record<string, ChoiceValue>;
  /**
   * The agent created earlier in a `create-agent` flow, so the round-trip after
   * a knowledge or skill detour can point back at *that* agent's card — the one
   * the reader just built — rather than the first in the gallery. Captured by
   * the coach from the builder URL and cleared at every flow start.
   */
  flowAgentId: string | null;
  /** The first-run walkthrough, from the top — the auto-start and a full replay. */
  openTour: () => void;
  /** The current page's highlights only — the header "?" button. */
  openPage: () => void;
  /** Start an interactive flow, clearing any offer, choices and captured id that led here. */
  openFlow: (flowId: FlowId) => void;
  /** Show the "Create X?" prompt for a flow, without starting it. */
  openOffer: (flowId: FlowId) => void;
  /** Dismiss the prompt — the reader declined, and nothing is recorded. */
  dismissOffer: () => void;
  /** Record a fork's answer and step past the question in one move. */
  answer: (questionId: string, value: ChoiceValue) => void;
  /** Remember the agent the flow just created, for the return leg of a detour. */
  setFlowAgentId: (agentId: string) => void;
  close: () => void;
  setIndex: (index: number) => void;
}

export const useOnboardingStore = create<OnboardingState>((set) => ({
  isOpen: false,
  index: 0,
  mode: "tour",
  flowId: null,
  offer: null,
  choices: {},
  flowAgentId: null,
  openTour: () => set({ isOpen: true, index: 0, mode: "tour", flowId: null }),
  openPage: () => set({ isOpen: true, index: 0, mode: "page", flowId: null }),
  openFlow: (flowId) =>
    set({
      isOpen: true,
      index: 0,
      mode: "flow",
      flowId,
      offer: null,
      choices: {},
      flowAgentId: null,
    }),
  openOffer: (flowId) => set({ offer: flowId }),
  dismissOffer: () => set({ offer: null }),
  // Advancing here rather than leaving it to the coach keeps the widening of the
  // step list and the move onto its first new step in one update: the recorded
  // answer brings the detour into the flow, and `index + 1` lands on it. A
  // question is never the flow's last step, so stepping past it always has
  // somewhere to go.
  answer: (questionId, value) =>
    set((state) => ({
      choices: { ...state.choices, [questionId]: value },
      index: state.index + 1,
    })),
  setFlowAgentId: (agentId) => set({ flowAgentId: agentId }),
  close: () => set({ isOpen: false }),
  setIndex: (index) => set({ index }),
}));
