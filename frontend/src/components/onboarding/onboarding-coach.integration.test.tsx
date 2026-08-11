import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OnboardingCoach } from "./onboarding-coach";
import type { OnboardingFlowState } from "@/hooks/use-onboarding-flow";
import type { FlowStep } from "@/lib/onboarding/flows";

const router = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  prefetch: vi.fn(),
  back: vi.fn(),
}));
const nav = vi.hoisted(() => ({ pathname: "/skills" }));
vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useRouter: () => router,
}));

// The DOM/query boundary; stubbed so the coach's orchestration is what is under
// test, not driver-less element hunting jsdom cannot do.
vi.mock("@/components/onboarding/spotlight", () => ({
  waitForElement: vi.fn(async () => document.createElement("div")),
  activateTab: vi.fn(),
}));

const flow = vi.hoisted(() => ({ state: null as OnboardingFlowState | null }));
vi.mock("@/hooks/use-onboarding-flow", () => ({
  useOnboardingFlow: () => flow.state,
}));

function step(overrides: Partial<FlowStep> = {}): FlowStep {
  return {
    id: "flow-skill-create",
    page: "/skills",
    target: "skills-new",
    interactive: true,
    signal: { kind: "created", resource: "skill" },
    ...overrides,
  };
}

function makeState(overrides: Partial<OnboardingFlowState> = {}): OnboardingFlowState {
  const one = step();
  return {
    isActive: true,
    flowId: "create-skill",
    steps: [one],
    step: one,
    index: 0,
    isLast: true,
    signalMet: false,
    next: vi.fn(),
    finish: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  nav.pathname = "/skills";
  flow.state = makeState();
});

describe("OnboardingCoach", () => {
  it("shows the current step's instruction card", () => {
    render(<OnboardingCoach />);
    expect(screen.getByText("Add your skill")).toBeInTheDocument();
  });

  it("closes the flow from the close button", async () => {
    const finish = vi.fn();
    flow.state = makeState({ finish });
    render(<OnboardingCoach />);
    await userEvent.click(screen.getByLabelText("Close"));
    expect(finish).toHaveBeenCalled();
  });

  it("advances the moment the resource is created", async () => {
    const next = vi.fn();
    flow.state = makeState({ signalMet: true, next });
    render(<OnboardingCoach />);
    await waitFor(() => expect(next).toHaveBeenCalled());
  });

  it("carries a Next for a step that has no create to wait on", async () => {
    const next = vi.fn();
    const descriptive = step({ signal: undefined });
    flow.state = makeState({ step: descriptive, steps: [descriptive], next });
    render(<OnboardingCoach />);
    // Last step, so the manual control reads Finish; clicking it advances.
    await userEvent.click(screen.getByRole("button", { name: "Finish" }));
    expect(next).toHaveBeenCalled();
  });

  it("lets the reader skip an optional step", async () => {
    const next = vi.fn();
    const optional = step({ optional: true });
    flow.state = makeState({ step: optional, steps: [optional], next });
    render(<OnboardingCoach />);
    await userEvent.click(screen.getByRole("button", { name: "Skip" }));
    expect(next).toHaveBeenCalled();
  });

  it("navigates to the step's page when the reader is elsewhere", async () => {
    nav.pathname = "/dashboard";
    render(<OnboardingCoach />);
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/skills"));
  });

  it("renders nothing when no flow is active", () => {
    flow.state = makeState({ isActive: false });
    const { container } = render(<OnboardingCoach />);
    expect(container).toBeEmptyDOMElement();
  });
});
