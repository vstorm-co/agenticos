import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { A2aPanel, a2aAddresses } from "./a2a-panel";
import type { Agent } from "@/types/agents";

const state = vi.hoisted(() => ({ mutate: vi.fn(), isPending: false }));

vi.mock("@/hooks", () => ({
  useAgent: () => ({ setA2a: { mutate: state.mutate, isPending: state.isPending } }),
}));
vi.mock("@/components/public-config/public-config-provider", () => ({
  usePublicConfig: () => ({ apiUrl: "https://api.acme.example/" }),
}));

function agent(overrides: Partial<Agent> = {}): Agent {
  return { id: "ag-1", current_version_id: "v1", a2a_enabled: false, ...overrides } as Agent;
}

beforeEach(() => {
  state.mutate.mockClear();
});

describe("A2aPanel", () => {
  it("serves a published agent when switched on", async () => {
    render(<A2aPanel agent={agent()} canManage />);

    expect(screen.getByText(/Turn it on to give this agent an agent card/)).toBeVisible();
    await userEvent.click(screen.getByRole("switch", { name: "Serve this agent over A2A" }));

    expect(state.mutate).toHaveBeenCalledWith(true);
  });

  it("shows the card and the endpoint once served", () => {
    render(<A2aPanel agent={agent({ a2a_enabled: true })} canManage />);

    expect(
      screen.getByText("https://api.acme.example/api/v1/a2a/ag-1/.well-known/agent-card.json"),
    ).toBeVisible();
    expect(screen.getByText("https://api.acme.example/api/v1/a2a/ag-1")).toBeVisible();
    expect(screen.getByText(/organization API key or an OAuth access token/)).toBeVisible();
  });

  it("asks for a publish before an agent can be served", () => {
    render(<A2aPanel agent={agent({ current_version_id: null })} canManage />);

    expect(screen.getByText(/Publish the agent first/)).toBeVisible();
    expect(screen.getByRole("switch")).toBeDisabled();
  });

  it("offers no switch to somebody who may not publish", () => {
    render(<A2aPanel agent={agent()} canManage={false} />);

    expect(screen.queryByRole("switch")).toBeNull();
  });
});

describe("a2aAddresses", () => {
  it("joins the API's address and the agent's id", () => {
    expect(a2aAddresses("https://api.example", "x")).toEqual({
      card: "https://api.example/api/v1/a2a/x/.well-known/agent-card.json",
      endpoint: "https://api.example/api/v1/a2a/x",
    });
  });
});
