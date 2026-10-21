import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { authoringRequest } from "@/test-utils/authoring";
import type { AuthoringRequest } from "@/types/authoring";
import { DescribeWithArchitect } from "./describe-with-architect";
import { ImproveSkillButton } from "./improve-skill-button";
import { SkillCheckButton } from "./skill-check-button";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
const state = vi.hoisted(() => ({
  runsView: true,
  latest: null as AuthoringRequest | null,
  enabled: true as boolean | null,
  assistant: { can_use: true, status: "ready", agent_id: "architect", name: "Architect" } as {
    can_use: boolean;
    status: string;
    agent_id: string | null;
    name: string;
  } | null,
  ask: vi.fn(),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => state.runsView }),
}));
vi.mock("@/hooks/use-organizations", () => ({
  useAiAssistance: () => ({ orgId: "org-1", enabled: state.enabled }),
}));
vi.mock("@/hooks/use-assistant", () => ({ useAssistant: () => ({ assistant: state.assistant }) }));
vi.mock("@/stores/architect-ask-store", () => ({
  useArchitectAskStore: (select: (value: { ask: (text: string) => void }) => unknown) =>
    select({ ask: state.ask }),
}));
vi.mock("@/hooks/use-eval-suites", () => ({ useAgentEvalSuites: () => ({ suites: [] }) }));
vi.mock("@/hooks/use-eval-runs", () => ({
  useEveryDataset: () => ({ datasets: [{ id: "ds-1", name: "Refund cases" }] }),
  useEveryAgent: () => ({ agents: [{ id: "agent-2", name: "Clerk" }] }),
}));
vi.mock("@/components/evals/estimate-summary", () => ({ EstimateSummary: () => <p>priced</p> }));
vi.mock("@/hooks/use-authoring", () => ({
  useSkillAuthoring: () => ({
    latest: state.latest,
    estimate: {
      mutateAsync: vi.fn().mockResolvedValue({
        runs: 2,
        rated_down: 1,
        calls: 1,
        estimate_usd: "0.01",
        affordable: true,
        reason: null,
      }),
    },
    start: { mutateAsync: vi.fn() },
    checkEstimate: {
      mutateAsync: () => Promise.resolve({ total_usd: "0.10", affordable: true }),
    },
    check: { mutateAsync: () => Promise.resolve({ id: "eval-3", agent_id: "agent-2" }) },
  }),
}));

beforeEach(() => {
  state.runsView = true;
  state.latest = null;
  state.enabled = true;
  state.assistant = { can_use: true, status: "ready", agent_id: "architect", name: "Architect" };
  state.ask = vi.fn();
});

describe("ImproveSkillButton", () => {
  it("asks before improving a skill", async () => {
    render(<ImproveSkillButton skillId="skill-1" />);
    await userEvent.click(screen.getByRole("button", { name: "Improve with the assistant" }));
    expect(await screen.findByText(/It will read 2 runs/)).toBeInTheDocument();
  });

  it("is off while AI assistance is, busy while it works, and says when it failed", () => {
    state.enabled = false;
    const { unmount } = render(<ImproveSkillButton skillId="skill-1" />);
    expect(screen.getByRole("button", { name: "Improve with the assistant" })).toBeDisabled();
    unmount();
    state.enabled = true;
    state.latest = authoringRequest({ status: "queued" });
    const second = render(<ImproveSkillButton skillId="skill-1" />);
    expect(screen.getByRole("button", { name: "Reading the runs…" })).toBeDisabled();
    second.unmount();
    state.latest = authoringRequest({ status: "failed", error: "No runs opened it" });
    render(<ImproveSkillButton skillId="skill-1" />);
    expect(screen.getByRole("alert")).toHaveTextContent("No runs opened it");
  });
});

describe("SkillCheckButton", () => {
  it("checks a skill change on the agent chosen, and goes to that run", async () => {
    render(<SkillCheckButton skillId="skill-1" proposalId="change-1" />);
    await userEvent.click(screen.getByRole("button", { name: "Check with evals" }));
    await userEvent.click(
      await screen.findByRole("combobox", { name: "Agent that uses the skill" }),
    );
    await userEvent.click(await screen.findByRole("option", { name: "Clerk" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Check against" }));
    await userEvent.click(await screen.findByRole("option", { name: "Refund cases" }));
    await screen.findByText("priced");
    await userEvent.click(screen.getByRole("button", { name: "Start the check" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/agents/agent-2/evals/eval-3"));
  });
});

describe("DescribeWithArchitect", () => {
  it("hands the description to the Architect and closes the dialog", async () => {
    const onAsked = vi.fn();
    render(<DescribeWithArchitect onAsked={onAsked} />);
    const send = screen.getByRole("button", { name: "Describe it to the Architect" });
    expect(send).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox"), "A refund helper");
    await userEvent.click(send);
    expect(state.ask).toHaveBeenCalledWith("Draft an agent for me: A refund helper");
    expect(onAsked).toHaveBeenCalled();
  });

  it("is absent while the Architect or AI assistance is off", () => {
    state.enabled = false;
    const { container, unmount } = render(<DescribeWithArchitect onAsked={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
    unmount();
    state.enabled = true;
    state.assistant = null;
    const second = render(<DescribeWithArchitect onAsked={vi.fn()} />);
    expect(second.container).toBeEmptyDOMElement();
  });

  it("is absent while the Architect has no model to answer with", () => {
    // A description sent to an Architect that cannot answer is lost with the dialog.
    state.assistant = {
      can_use: true,
      status: "needs_model",
      agent_id: "architect",
      name: "Architect",
    };
    const { container } = render(<DescribeWithArchitect onAsked={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});
