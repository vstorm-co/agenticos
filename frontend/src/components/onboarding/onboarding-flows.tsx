"use client";

import { useEffect } from "react";

import { CreationOffer } from "@/components/onboarding/creation-offer";
import { OnboardingCoach } from "@/components/onboarding/onboarding-coach";
import { stashFlow, takeStashedFlow } from "@/lib/onboarding/resume";
// The specific module, not the `@/stores` barrel — this mounts in the dashboard
// layout, and the barrel would drag the store into every test that partially
// mocks `@/stores`.
import { useOnboardingStore } from "@/stores/onboarding-store";

/**
 * The Phase-2 interactive layer, mounted once in the dashboard layout beside the
 * passive `OnboardingTour`.
 *
 * The offer prompt is always mounted — it renders only when the store holds one,
 * and reads nothing costly otherwise. The coach is mounted *only* while a flow
 * runs, so the resource-count queries `useOnboardingFlow` fires do not run on
 * every page; the moment the flow ends the coach unmounts and, with it, its
 * per-step baseline, so a flow reopened later starts clean.
 *
 * It is also where a flow survives a full-page navigation, because it is the one
 * part of the feature mounted whether or not a flow is running. Connecting an MCP
 * server over OAuth leaves the app for the provider's consent screen and returns
 * through a second load, which empties this store — so the walk is stowed on the
 * way out and taken back on the way in (`lib/onboarding/resume`). The store itself
 * stays non-durable: this is one tab, one redirect, read once.
 */
export function OnboardingFlows() {
  const isOpen = useOnboardingStore((state) => state.isOpen);
  const mode = useOnboardingStore((state) => state.mode);
  const resume = useOnboardingStore((state) => state.resume);

  useEffect(() => {
    const stashed = takeStashedFlow();
    if (stashed) resume(stashed);
  }, [resume]);

  // `pagehide`, not `beforeunload`: it fires for a same-tab navigation as well as
  // a close, and it does not ask the browser for permission to run.
  useEffect(() => {
    const onHide = () => {
      const state = useOnboardingStore.getState();
      if (!state.isOpen || state.mode !== "flow" || state.flowId === null) return;
      stashFlow({
        flowId: state.flowId,
        index: state.index,
        choices: state.choices,
        flowAgentId: state.flowAgentId,
      });
    };
    window.addEventListener("pagehide", onHide);
    return () => window.removeEventListener("pagehide", onHide);
  }, []);

  return (
    <>
      <CreationOffer />
      {isOpen && mode === "flow" && <OnboardingCoach />}
    </>
  );
}
