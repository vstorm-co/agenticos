import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OnboardingFlows } from "./onboarding-flows";
import { stashFlow, takeStashedFlow } from "@/lib/onboarding/resume";
import { useOnboardingStore } from "@/stores/onboarding-store";

// The coach and the offer are covered by their own suites, and both reach for
// queries this one has no client for. What is under test here is the wiring that
// carries a walk across a full page load.
vi.mock("./onboarding-coach", () => ({ OnboardingCoach: () => <div data-testid="coach" /> }));
vi.mock("./creation-offer", () => ({ CreationOffer: () => null }));

const RUNNING = {
  flowId: "create-agent" as const,
  index: 12,
  choices: { "flow-agent-mcp-ask": "yes" as const },
  flowAgentId: "agent-7",
};

beforeEach(() => {
  sessionStorage.clear();
  useOnboardingStore.setState({
    isOpen: false,
    index: 0,
    mode: "tour",
    flowId: null,
    offer: null,
    choices: {},
    flowAgentId: null,
  });
});

describe("OnboardingFlows", () => {
  it("picks a stowed flow back up on the load after a redirect", () => {
    // Connecting an MCP server over OAuth leaves the app for the provider's consent
    // screen and returns through a second full load, which empties this store — so
    // the rest of a half-built agent (its limits, its publish, its first run) was
    // silently abandoned even though the connection succeeded.
    stashFlow(RUNNING);
    render(<OnboardingFlows />);

    expect(useOnboardingStore.getState()).toMatchObject({
      isOpen: true,
      mode: "flow",
      ...RUNNING,
    });
    // Read once: a later reload starts clean rather than reopening the walk.
    expect(takeStashedFlow()).toBeNull();
  });

  it("starts nothing when no flow was stowed", () => {
    render(<OnboardingFlows />);
    expect(useOnboardingStore.getState().isOpen).toBe(false);
  });

  it("stows a running flow as the page is replaced", () => {
    render(<OnboardingFlows />);
    useOnboardingStore.getState().resume(RUNNING);

    window.dispatchEvent(new Event("pagehide"));

    expect(takeStashedFlow()).toEqual(RUNNING);
  });

  it("stows nothing when no flow is running", () => {
    render(<OnboardingFlows />);
    useOnboardingStore.getState().openPage(); // a "?" walk, not a flow

    window.dispatchEvent(new Event("pagehide"));

    expect(takeStashedFlow()).toBeNull();
  });

  it("mounts the coach only while a flow runs", () => {
    const { queryByTestId, rerender } = render(<OnboardingFlows />);
    expect(queryByTestId("coach")).toBeNull();

    useOnboardingStore.getState().openFlow("create-agent");
    rerender(<OnboardingFlows />);
    expect(queryByTestId("coach")).toBeInTheDocument();
  });
});
