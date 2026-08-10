import { beforeEach, describe, expect, it } from "vitest";

import { useOnboardingStore } from "./onboarding-store";

describe("useOnboardingStore", () => {
  beforeEach(() => useOnboardingStore.setState({ isOpen: false, index: 0 }));

  it("restart opens at the first step, wherever the walkthrough had reached", () => {
    useOnboardingStore.setState({ index: 3 });
    useOnboardingStore.getState().restart();
    expect(useOnboardingStore.getState()).toMatchObject({ isOpen: true, index: 0 });
  });

  it("close hides the walkthrough without moving the step", () => {
    useOnboardingStore.setState({ isOpen: true, index: 2 });
    useOnboardingStore.getState().close();
    expect(useOnboardingStore.getState()).toMatchObject({ isOpen: false, index: 2 });
  });

  it("setIndex moves to a step", () => {
    useOnboardingStore.getState().setIndex(4);
    expect(useOnboardingStore.getState().index).toBe(4);
  });
});
