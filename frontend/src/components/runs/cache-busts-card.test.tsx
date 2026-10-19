import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CacheByAgentModel } from "@/types/runs";
import { CacheBustsCard } from "./cache-busts-card";

vi.mock("@/components/agents/agent-avatar", () => ({ AgentAvatar: () => <span /> }));

const row = (overrides: Partial<CacheByAgentModel>): CacheByAgentModel => ({
  agent_id: "a-1",
  agent_slug: "clerk",
  agent_name: "Billing clerk",
  model_label: "claude-sonnet-4-5",
  busts: 4,
  expiries: 0,
  missed_tokens: 18000,
  run_count: 2,
  ...overrides,
});

describe("the prompt cache card", () => {
  it("lists each agent on each model with its busts, expiries and re-sent tokens", () => {
    render(
      <CacheBustsCard
        rows={[row({}), row({ model_label: null, busts: 0, expiries: 1, missed_tokens: 500 })]}
      />,
    );

    expect(screen.getByText("Prompt cache")).toBeInTheDocument();
    const [, first, second] = screen.getAllByRole("row");
    expect(within(first!).getByText("claude-sonnet-4-5")).toBeInTheDocument();
    expect(first).toHaveTextContent("Billing clerk");
    expect(first).toHaveTextContent("18,000");
    expect(within(second!).getByText("model not recorded")).toBeInTheDocument();
  });

  it("is not drawn while every cache held", () => {
    const { container } = render(<CacheBustsCard rows={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
