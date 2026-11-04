import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { WatchAgentFields } from "./watch-agent-fields";
import type { AgentAvatarProps } from "@/components/agents/agent-avatar";

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
  }),
  useAgentEnvironments: () => ({ environments: [] }),
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
