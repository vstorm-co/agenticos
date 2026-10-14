import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui";
import type { Agent } from "@/types/agents";
import { SystemAgentsSection } from "./system-agents-section";

const state = vi.hoisted(() => ({ agents: [] as Partial<Agent>[] }));
vi.mock("@/hooks/use-agents", () => ({
  useSystemAgents: () => ({ agents: state.agents, total: state.agents.length }),
}));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => true }) }));
vi.mock("./agent-card", () => ({
  AgentCard: ({ agent, canEdit }: { agent: Agent; canEdit: boolean }) => (
    <div data-testid="card" data-can-edit={String(canEdit)}>
      {agent.name}
    </div>
  ),
}));

beforeEach(() => {
  state.agents = [{ id: "j1", name: "Eval judge", system_key: "eval_judge" }];
});

function section() {
  return render(
    <TooltipProvider>
      <SystemAgentsSection />
    </TooltipProvider>,
  );
}

/** The platform's agents sit folded under the organization's, opened on demand. */
describe("SystemAgentsSection", () => {
  it("starts folded, and opens onto cards an editor can open", async () => {
    section();
    const toggle = screen.getByRole("button", { name: "System agent (1)" });

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("card")).toBeNull();

    await userEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("card")).toHaveTextContent("Eval judge");
    expect(screen.getByTestId("card")).toHaveAttribute("data-can-edit", "true");
  });

  it("is absent while the organization has none", () => {
    state.agents = [];
    const { container } = section();

    expect(container).toBeEmptyDOMElement();
  });
});
