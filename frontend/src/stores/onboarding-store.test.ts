import { beforeEach, describe, expect, it } from "vitest";

import { useOnboardingStore } from "./onboarding-store";

describe("useOnboardingStore", () => {
  beforeEach(() => useOnboardingStore.setState({ isOpen: false, index: 0, mode: "tour" }));

  it("openTour opens the full walkthrough at the first step, wherever it had reached", () => {
    useOnboardingStore.setState({ index: 3, mode: "page" });
    useOnboardingStore.getState().openTour();
    expect(useOnboardingStore.getState()).toMatchObject({ isOpen: true, index: 0, mode: "tour" });
  });

  it("openPage opens in page mode at the first step", () => {
    useOnboardingStore.setState({ index: 3 });
    useOnboardingStore.getState().openPage();
    expect(useOnboardingStore.getState()).toMatchObject({ isOpen: true, index: 0, mode: "page" });
  });

  it("close hides the walkthrough without moving the step or the mode", () => {
    useOnboardingStore.setState({ isOpen: true, index: 2, mode: "page" });
    useOnboardingStore.getState().close();
    expect(useOnboardingStore.getState()).toMatchObject({ isOpen: false, index: 2, mode: "page" });
  });

  it("setIndex moves to a step", () => {
    useOnboardingStore.getState().setIndex(4);
    expect(useOnboardingStore.getState().index).toBe(4);
  });
});
