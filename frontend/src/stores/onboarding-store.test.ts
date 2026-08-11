import { beforeEach, describe, expect, it } from "vitest";

import { useOnboardingStore } from "./onboarding-store";

describe("useOnboardingStore", () => {
  beforeEach(() =>
    useOnboardingStore.setState({
      isOpen: false,
      index: 0,
      mode: "tour",
      flowId: null,
      offer: null,
    }),
  );

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

  it("openTour and openPage clear a flow that was running", () => {
    useOnboardingStore.setState({ mode: "flow", flowId: "create-skill" });
    useOnboardingStore.getState().openTour();
    expect(useOnboardingStore.getState().flowId).toBeNull();

    useOnboardingStore.setState({ mode: "flow", flowId: "create-kb" });
    useOnboardingStore.getState().openPage();
    expect(useOnboardingStore.getState().flowId).toBeNull();
  });

  it("openFlow starts the named flow at its first step", () => {
    useOnboardingStore.setState({ index: 5, mode: "page", offer: "create-skill" });
    useOnboardingStore.getState().openFlow("create-skill");
    expect(useOnboardingStore.getState()).toMatchObject({
      isOpen: true,
      index: 0,
      mode: "flow",
      flowId: "create-skill",
      // Accepting an offer starts the flow, so the prompt is gone.
      offer: null,
    });
  });

  it("openOffer shows the prompt without opening a walkthrough", () => {
    useOnboardingStore.getState().openOffer("create-org");
    expect(useOnboardingStore.getState()).toMatchObject({ offer: "create-org", isOpen: false });
  });

  it("dismissOffer clears the prompt and records nothing", () => {
    useOnboardingStore.setState({ offer: "create-mcp" });
    useOnboardingStore.getState().dismissOffer();
    expect(useOnboardingStore.getState().offer).toBeNull();
  });
});
