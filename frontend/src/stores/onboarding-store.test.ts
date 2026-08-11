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
      choices: {},
      flowAgentId: null,
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

  it("openFlow starts the named flow at its first step, clearing a prior flow's forks", () => {
    useOnboardingStore.setState({
      index: 5,
      mode: "page",
      offer: "create-skill",
      choices: { "flow-agent-knowledge-ask": "yes" },
      flowAgentId: "agent-42",
    });
    useOnboardingStore.getState().openFlow("create-skill");
    expect(useOnboardingStore.getState()).toMatchObject({
      isOpen: true,
      index: 0,
      mode: "flow",
      flowId: "create-skill",
      // Accepting an offer starts the flow, so the prompt is gone.
      offer: null,
      // A fresh flow answers its own forks and captures its own agent.
      choices: {},
      flowAgentId: null,
    });
  });

  it("answer records a fork and steps past the question in one move", () => {
    useOnboardingStore.setState({ mode: "flow", flowId: "create-agent", index: 4 });
    useOnboardingStore.getState().answer("flow-agent-knowledge-ask", "yes");
    expect(useOnboardingStore.getState().choices).toEqual({ "flow-agent-knowledge-ask": "yes" });
    // The detour is now in the flow and the step after the question is where the
    // reader lands.
    expect(useOnboardingStore.getState().index).toBe(5);
  });

  it("answer keeps earlier forks when a second one is answered", () => {
    useOnboardingStore.setState({
      mode: "flow",
      flowId: "create-agent",
      index: 9,
      choices: { "flow-agent-knowledge-ask": "yes" },
    });
    useOnboardingStore.getState().answer("flow-agent-skills-ask", "skip");
    expect(useOnboardingStore.getState().choices).toEqual({
      "flow-agent-knowledge-ask": "yes",
      "flow-agent-skills-ask": "skip",
    });
  });

  it("setFlowAgentId remembers the agent the flow created", () => {
    useOnboardingStore.getState().setFlowAgentId("agent-7");
    expect(useOnboardingStore.getState().flowAgentId).toBe("agent-7");
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
