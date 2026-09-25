import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentVersionPicker, type AgentVersionRef } from "./agent-version-picker";

const useAgentsMock = vi.fn();
const useAllAgentVersionsMock = vi.fn();

vi.mock("@/hooks", () => ({
  useAgents: () => useAgentsMock(),
  useAllAgentVersions: (agentId: string | null) => useAllAgentVersionsMock(agentId),
}));

const AGENTS = [
  { id: "a1", name: "Support" },
  { id: "a2", name: "Billing" },
];
const VERSIONS = [
  { id: "v1", version: 1 },
  { id: "v2", version: 2 },
];

beforeEach(() => {
  vi.clearAllMocks();
  useAgentsMock.mockReturnValue({ agents: AGENTS, isLoading: false });
  useAllAgentVersionsMock.mockReturnValue({ versions: VERSIONS, isLoading: false });
});

function mount(value: AgentVersionRef, props: Partial<{ disabled: boolean; error: string }> = {}) {
  const onChange = vi.fn();
  render(<AgentVersionPicker value={value} onChange={onChange} {...props} />);
  return onChange;
}

describe("AgentVersionPicker", () => {
  it("choosing an agent clears the pinned version", async () => {
    const onChange = mount({ agent_id: "a1", version_id: "v1" });

    await userEvent.click(screen.getByRole("combobox", { name: "Agent" }));
    await userEvent.click(screen.getByRole("option", { name: "Billing" }));

    expect(onChange).toHaveBeenCalledWith({ agent_id: "a2", version_id: null });
  });

  it("pins the chosen version of the chosen agent", async () => {
    const onChange = mount({ agent_id: "a1", version_id: null });

    await userEvent.click(screen.getByRole("combobox", { name: "Version" }));
    await userEvent.click(screen.getByRole("option", { name: "Version 2" }));

    expect(onChange).toHaveBeenCalledWith({ agent_id: "a1", version_id: "v2" });
  });

  it("keeps a pinned agent visible when it names no agent the caller can see", () => {
    mount({ agent_id: "gone", version_id: "v9" });

    expect(screen.getByText("The pinned agent is no longer available.")).toBeVisible();
    expect(screen.getByText("gone")).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Version" })).toBeDisabled();
  });

  it("flags a chosen agent with no version pinned as unfinished", () => {
    mount({ agent_id: "a1", version_id: null });

    expect(screen.getByText("Pick a version to pin.")).toBeVisible();
  });

  it("warns when the pinned version names no version the agent still publishes", () => {
    mount({ agent_id: "a1", version_id: "v9" });

    expect(screen.getByText("The pinned version is no longer available.")).toBeVisible();
    expect(screen.getByText("v9")).toBeVisible();
  });

  it("shows no orphaned-version warning while the version list is still loading", () => {
    useAllAgentVersionsMock.mockReturnValue({ versions: [], isLoading: true });
    mount({ agent_id: "a1", version_id: "v9" });

    expect(screen.queryByText("The pinned version is no longer available.")).toBeNull();
  });

  it("keeps the version step disabled until an agent is chosen", () => {
    mount({ agent_id: null, version_id: null });

    expect(screen.getByRole("combobox", { name: "Version" })).toBeDisabled();
  });

  it("says so when the organization has no agents", () => {
    useAgentsMock.mockReturnValue({ agents: [], isLoading: false });
    mount({ agent_id: null, version_id: null });

    expect(screen.getByText("No agents to choose from.")).toBeVisible();
  });

  it("says so when the chosen agent has no published versions", () => {
    useAllAgentVersionsMock.mockReturnValue({ versions: [], isLoading: false });
    mount({ agent_id: "a1", version_id: null });

    expect(screen.getByText("This agent has no published versions yet.")).toBeVisible();
    expect(screen.queryByText("Pick a version to pin.")).toBeNull();
  });

  it("shows a field-scoped validation message", () => {
    mount({ agent_id: "a1", version_id: "v1" }, { error: "Required" });

    expect(screen.getByText("Required")).toBeVisible();
  });

  it("is inert for a caller who may not edit the workflow", () => {
    mount({ agent_id: "a1", version_id: "v1" }, { disabled: true });

    expect(screen.getByRole("combobox", { name: "Agent" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Version" })).toBeDisabled();
  });

  it("draws no empty or missing notices while the lists are still loading", () => {
    useAgentsMock.mockReturnValue({ agents: [], isLoading: true });
    useAllAgentVersionsMock.mockReturnValue({ versions: [], isLoading: true });
    mount({ agent_id: "a1", version_id: null });

    expect(screen.queryByText("No agents to choose from.")).toBeNull();
    expect(screen.queryByText("This agent has no published versions yet.")).toBeNull();
  });
});
