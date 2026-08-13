import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OnboardingCoach } from "./onboarding-coach";
import { waitForElement } from "./spotlight";
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

// The DOM/query boundary; the element hunt and tab reveal are stubbed so the
// coach's orchestration is what is under test, not driver-less DOM work jsdom
// cannot do. `spotlightPath` is kept real — the freeze layer calls it on render.
vi.mock("@/components/onboarding/spotlight", async (importActual) => {
  const actual = await importActual<typeof import("./spotlight")>();
  return {
    ...actual,
    waitForElement: vi.fn(async () => document.createElement("div")),
    activateTab: vi.fn(),
  };
});

const flow = vi.hoisted(() => ({ state: null as OnboardingFlowState | null }));
vi.mock("@/hooks/use-onboarding-flow", () => ({
  useOnboardingFlow: () => flow.state,
}));

function step(overrides: Partial<FlowStep> = {}): FlowStep {
  return {
    id: "flow-skill-create",
    page: "/skills",
    target: "skills-new",
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
    answer: vi.fn(),
    openFlow: vi.fn(),
    flowAgentId: null,
    setFlowAgentId: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  // `clearAllMocks` wipes the default implementation a test may have replaced.
  vi.mocked(waitForElement).mockImplementation(async () => document.createElement("div"));
  // A dialog a prior test appended to simulate an open modal would leak forward.
  document.querySelectorAll('[role="dialog"][data-state]').forEach((node) => node.remove());
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

  it("navigates to the step's page when the reader is elsewhere", async () => {
    nav.pathname = "/dashboard";
    render(<OnboardingCoach />);
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/skills"));
  });

  it("carries the reader back to the built agent for a builder step left behind", async () => {
    // A fork that crossed to another section to ask leaves the reader there on
    // Skip; the next builder step must return them to the agent this flow built
    // rather than hunt for its control on the wrong page under the freeze.
    nav.pathname = "/skills";
    const builderStep = step({ id: "flow-agent-tools", page: "agent-builder", signal: undefined });
    flow.state = makeState({
      flowId: "create-agent",
      step: builderStep,
      steps: [builderStep],
      flowAgentId: "a-42",
    });
    render(<OnboardingCoach />);
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/agents/a-42"));
  });

  it("renders nothing when no flow is active", () => {
    flow.state = makeState({ isActive: false });
    const { container } = render(<OnboardingCoach />);
    expect(container).toBeEmptyDOMElement();
  });

  it("freezes the page while a step is in progress", async () => {
    render(<OnboardingCoach />);
    await waitFor(() => expect(document.querySelector("[data-coach-freeze]")).toBeInTheDocument());
  });

  it("lifts the freeze while a modal dialog is open, so its own overlay owns the screen", async () => {
    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("data-state", "open");
    document.body.appendChild(dialog);

    render(<OnboardingCoach />);
    // The card still guides the reader; only the second freeze layer is gone.
    await screen.findByText("Add your skill");
    await waitFor(() => expect(document.querySelector("[data-coach-freeze]")).toBeNull());
  });

  it("draws the travelling highlight ring while a step is showing", async () => {
    render(<OnboardingCoach />);
    await waitFor(() => expect(document.querySelector("[data-coach-ring]")).toBeInTheDocument());
  });

  it("keeps guiding inside an open dialog for an in-overlay step", async () => {
    // A field step points into the dialog: the freeze stays down (the dialog's
    // own overlay dims the page) but the ring still renders, framing the field.
    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("data-state", "open");
    document.body.appendChild(dialog);

    const field = step({ id: "flow-skill-field-name", inOverlay: true, signal: undefined });
    flow.state = makeState({ step: field, steps: [field] });
    render(<OnboardingCoach />);
    await screen.findByText("Name it");
    await waitFor(() => expect(document.querySelector("[data-coach-ring]")).toBeInTheDocument());
    expect(document.querySelector("[data-coach-freeze]")).toBeNull();
  });

  it("advances an opened step the moment a dialog opens on top of the count it began with", async () => {
    const next = vi.fn();
    const opener = step({ id: "flow-skill-create", signal: { kind: "opened" } });
    flow.state = makeState({ step: opener, steps: [opener], next });
    render(<OnboardingCoach />);
    await screen.findByText("Add your skill");
    expect(next).not.toHaveBeenCalled();

    // The reader clicks the trigger and the create dialog mounts.
    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("data-state", "open");
    document.body.appendChild(dialog);
    await waitFor(() => expect(next).toHaveBeenCalled());
  });

  it("lifts the freeze while a Radix popper is open, so a picker can be used", async () => {
    // A popover/dropdown/select portals a wrapper the coach must step aside for,
    // or its ring and dim would sit over the picker the step points at.
    const popper = document.createElement("div");
    popper.setAttribute("data-radix-popper-content-wrapper", "");
    document.body.appendChild(popper);

    render(<OnboardingCoach />);
    await screen.findByText("Add your skill");
    await waitFor(() => expect(document.querySelector("[data-coach-freeze]")).toBeNull());
  });

  it("asks a fork with Yes/Skip and records the answer, showing no ring", async () => {
    const answer = vi.fn();
    const fork = step({
      id: "flow-agent-knowledge-ask",
      question: true,
      signal: undefined,
      target: undefined,
      page: undefined,
    });
    flow.state = makeState({ flowId: "create-agent", step: fork, steps: [fork], answer });
    render(<OnboardingCoach />);

    // A fork points at nothing, so it dims the page whole and draws no ring.
    expect(document.querySelector("[data-coach-ring]")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Yes, let's do it" }));
    expect(answer).toHaveBeenCalledWith("flow-agent-knowledge-ask", "yes");

    await userEvent.click(screen.getByRole("button", { name: "Skip" }));
    expect(answer).toHaveBeenCalledWith("flow-agent-knowledge-ask", "skip");
  });

  it("cancels Space on the guarded submit, so Tab-then-Space cannot create the resource early", async () => {
    // The freeze blocks pointers, not Tab. A focused submit button activates on
    // Space as well as Enter, so a keyboard user could Tab to Create and press
    // Space, jumping past the field steps — the dead-end the guard exists to stop.
    const guarded = step({ blockSubmit: "skills-new" });
    flow.state = makeState({ step: guarded, steps: [guarded] });
    render(<OnboardingCoach />);
    await screen.findByText("Add your skill");

    const submit = document.createElement("button");
    submit.type = "submit";
    submit.setAttribute("data-tour", "skills-new");
    document.body.appendChild(submit);
    submit.focus();
    // fireEvent returns false when a handler called preventDefault.
    expect(fireEvent.keyDown(submit, { key: " " })).toBe(false);

    // Space must survive in a text field — there it types a space, not a submit.
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();
    expect(fireEvent.keyDown(input, { key: " " })).toBe(true);
  });

  it("hands a fork's Yes off to another flow when it opensFlow", async () => {
    // The chat run's "build an agent first?" fork opens create-agent rather than
    // revealing a detour, so Yes calls openFlow, not answer.
    const openFlow = vi.fn();
    const answer = vi.fn();
    const fork = step({
      id: "flow-chat-needs-agent",
      question: true,
      opensFlow: "create-agent",
      signal: undefined,
      target: undefined,
      page: undefined,
    });
    flow.state = makeState({ flowId: "explore-chat", step: fork, steps: [fork], openFlow, answer });
    render(<OnboardingCoach />);

    await userEvent.click(screen.getByRole("button", { name: "Yes, let's do it" }));
    expect(openFlow).toHaveBeenCalledWith("create-agent");
    expect(answer).not.toHaveBeenCalled();

    // Skip still steps over it within this flow rather than handing off.
    await userEvent.click(screen.getByRole("button", { name: "Skip" }));
    expect(answer).toHaveBeenCalledWith("flow-chat-needs-agent", "skip");
  });
});
