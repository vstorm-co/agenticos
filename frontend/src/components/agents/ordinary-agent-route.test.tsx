import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrdinaryAgentRoute } from "./ordinary-agent-route";
import type { AgentKind } from "@/types/agents";

const state = vi.hoisted(() => ({
  agent: undefined as { id: string; name: string; kind: AgentKind } | undefined,
}));

vi.mock("@/hooks/use-agents", () => ({ useAgent: () => ({ agent: state.agent }) }));

function mount() {
  render(
    <OrdinaryAgentRoute agentId="a1">
      <p>The Improve wizard</p>
    </OrdinaryAgentRoute>,
  );
}

beforeEach(() => {
  state.agent = undefined;
});

describe("a page only an ordinary agent has", () => {
  it("renders as it would while the agent is loading", () => {
    mount();

    expect(screen.getByText("The Improve wizard")).toBeInTheDocument();
  });

  it("renders for an ordinary agent", () => {
    state.agent = { id: "a1", name: "Support", kind: "agent" };
    mount();

    expect(screen.getByText("The Improve wizard")).toBeInTheDocument();
  });

  it("says why a system agent has none, and leads back to its page", () => {
    state.agent = { id: "a1", name: "Eval judge", kind: "judge" };
    mount();

    expect(screen.queryByText("The Improve wizard")).toBeNull();
    expect(screen.getByRole("heading", { name: "Eval judge is a system agent" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Open its page" })).toHaveAttribute(
      "href",
      "/agents/a1",
    );
  });
});
