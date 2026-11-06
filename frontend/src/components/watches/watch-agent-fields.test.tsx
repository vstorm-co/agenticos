import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WatchAgentFields, WatchExecutionFields } from "./watch-agent-fields";
import type { AgentAvatarProps } from "@/components/agents/agent-avatar";

const failures = vi.hoisted(() => ({
  agents: null as Error | null,
  environments: null as Error | null,
  retryAgents: vi.fn(),
  retryEnvironments: vi.fn(),
}));
beforeEach(() => {
  vi.clearAllMocks();
  failures.agents = null;
  failures.environments = null;
});
vi.mock("@/hooks", () => ({
  useAgents: () => ({
    agents: [
      {
        id: "a-monitor",
        name: "Monitor",
        slug: "monitor",
        can_run: true,
        current_version_id: "v1",
        has_avatar: true,
        avatar_color: 4,
      },
    ],
    isLoading: false,
    error: failures.agents,
    refetch: failures.retryAgents,
  }),
  useAgentEnvironments: () => ({
    environments: [
      { id: "default", is_default: true },
      { id: "prod", is_default: false },
    ],
    error: failures.environments,
    refetch: failures.retryEnvironments,
  }),
}));

vi.mock("@/components/agents/agent-avatar", () => ({
  AgentAvatar: ({ agentId, slug, hasAvatar, colorSlot }: AgentAvatarProps) => (
    <span
      data-testid="agent-avatar"
      data-agent={agentId}
      data-slug={slug}
      data-uploaded={String(hasAvatar)}
      data-color={colorSlot}
    />
  ),
}));

function Picker() {
  const [agentId, setAgentId] = useState("");
  return <WatchAgentFields agentId={agentId} onAgent={setAgentId} disabled={false} />;
}

describe("watch agent identity", () => {
  it("shows the same agent portrait in the options and the selected value", async () => {
    render(<Picker />);
    const trigger = screen.getByRole("combobox", { name: "Agent" });
    await userEvent.click(trigger);
    const option = await screen.findByRole("option", { name: "Monitor" });
    const portrait = within(option).getByTestId("agent-avatar");
    expect(portrait).toHaveAttribute("data-agent", "a-monitor");
    expect(portrait).toHaveAttribute("data-slug", "monitor");
    expect(portrait).toHaveAttribute("data-uploaded", "true");
    expect(portrait).toHaveAttribute("data-color", "4");
    await userEvent.click(option);
    expect(trigger).toHaveTextContent("Monitor");
    expect(within(trigger).getByTestId("agent-avatar")).toHaveAttribute("data-agent", "a-monitor");
  });
});

vi.mock("@/components/triggers/version-field", () => ({
  VersionField: ({ onChange }: { onChange: (id: string | null) => void }) => (
    <button onClick={() => onChange("version")}>Pin published version</button>
  ),
}));
vi.mock("@/components/triggers/environment-field", () => ({
  DEFAULT_ENV: "default",
  EnvironmentField: ({ onChange }: { onChange: (id: string) => void }) => (
    <>
      <button onClick={() => onChange("prod")}>Use named environment</button>
      <button onClick={() => onChange("default")}>Use default environment</button>
    </>
  ),
}));
it("retries a failed agent list without silently choosing a replacement", async () => {
  failures.agents = new Error("List failed");
  render(<Picker />);
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(failures.retryAgents).toHaveBeenCalled();
});
it("switches between a named environment and the default pinned version explicitly", async () => {
  const environment = vi.fn(),
    version = vi.fn();
  const props = {
    agentId: "a-monitor",
    environmentId: null,
    pinnedVersionId: null,
    onEnvironment: environment,
    onVersion: version,
    onVersionValid: vi.fn(),
  };
  failures.environments = new Error("Environments unavailable");
  const view = render(<WatchExecutionFields {...props} error="Select a current version" />);
  expect(screen.getByText("Select a current version")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(failures.retryEnvironments).toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Use named environment" }));
  expect(environment).toHaveBeenLastCalledWith("prod");
  await userEvent.click(screen.getByRole("button", { name: "Use default environment" }));
  expect(environment).toHaveBeenLastCalledWith(null);
  await userEvent.click(screen.getByRole("button", { name: "Pin published version" }));
  expect(version).toHaveBeenCalledWith("version");
  view.rerender(<WatchExecutionFields {...props} environmentId="prod" />);
  expect(screen.queryByRole("button", { name: "Pin published version" })).not.toBeInTheDocument();
  view.rerender(<WatchExecutionFields {...props} agentId="" />);
  expect(screen.queryByRole("button", { name: "Use named environment" })).not.toBeInTheDocument();
});
