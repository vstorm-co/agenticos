import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RemoteAgentsPage from "./page";
import type { ExternalAgent } from "@/types/external-agents";

const state = vi.hoisted(() => ({
  agents: [] as ExternalAgent[],
  isLoading: false,
  error: null as string | null,
  canManage: true,
}));

vi.mock("@/hooks", () => ({
  useExternalAgents: () => ({
    agents: state.agents,
    isLoading: state.isLoading,
    error: state.error,
    register: vi.fn(),
    refresh: vi.fn(),
    remove: vi.fn(),
  }),
  usePermissions: () => ({ can: () => state.canManage, isLoading: false }),
  useSecrets: () => ({ secrets: [], create: { mutate: vi.fn(), isPending: false } }),
}));

beforeEach(() => {
  state.agents = [];
  state.isLoading = false;
  state.error = null;
  state.canManage = true;
});

describe("the remote agents page", () => {
  it("says what to do when none is registered, and opens the form", async () => {
    render(<RemoteAgentsPage />);

    expect(screen.getByText("No remote agents yet")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Register an agent" }));
    expect(screen.getByRole("dialog", { name: "Register a remote agent" })).toBeVisible();
  });

  it("lists what is registered, with its count", () => {
    state.agents = [
      {
        id: "ea-1",
        slug: "reviewer",
        name: "Contract Reviewer",
        description: "",
        card_url: "https://agents.example.com",
        endpoint_url: "https://agents.example.com/a2a",
        secret_id: null,
        skills: [],
        can_manage: true,
        created_at: "2026-10-17T00:00:00Z",
        updated_at: null,
      },
    ];
    render(<RemoteAgentsPage />);

    expect(screen.getByText("Contract Reviewer")).toBeVisible();
    expect(screen.getByText("1 registered")).toBeVisible();
  });

  it("shows a refusal where the list would be, and a skeleton while it loads", () => {
    state.error = "The remote agents could not be loaded.";
    const { rerender } = render(<RemoteAgentsPage />);
    expect(screen.getByText("The remote agents could not be loaded.")).toBeVisible();

    state.error = null;
    state.isLoading = true;
    rerender(<RemoteAgentsPage />);
    expect(screen.queryByText("No remote agents yet")).toBeNull();
  });

  it("offers no registration to somebody who may only look", () => {
    state.canManage = false;
    render(<RemoteAgentsPage />);
    expect(screen.queryByRole("button", { name: "Register an agent" })).toBeNull();
  });
});
