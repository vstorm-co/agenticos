"use client";

import { CreationOffer } from "@/components/onboarding/creation-offer";
import { OnboardingCoach } from "@/components/onboarding/onboarding-coach";
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
 */
export function OnboardingFlows() {
  const isOpen = useOnboardingStore((state) => state.isOpen);
  const mode = useOnboardingStore((state) => state.mode);

  return (
    <>
      <CreationOffer />
      {isOpen && mode === "flow" && <OnboardingCoach />}
    </>
  );
}
