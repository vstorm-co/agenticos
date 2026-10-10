import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";

import { AddToAgent } from "./add-to-agent";

const { can, agents, mutateAsync, push } = vi.hoisted(() => ({
  can: vi.fn(),
  agents: vi.fn(),
  mutateAsync: vi.fn(),
  push: vi.fn(),
}));

vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can }),
  useAgents: () => agents(),
  useAddToAgent: () => ({ mutateAsync, isPending: false }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), info: vi.fn(), error: vi.fn() } }));

const SUPPORT = {
  id: "a1",
  slug: "support",
  name: "Support",
  has_avatar: false,
  avatar_color: null,
};

function renderIt() {
  render(<AddToAgent resource={{ kind: "skill", id: "s1" }} name="refunds" />);
}

describe("AddToAgent", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    can.mockReturnValue(true);
    agents.mockReturnValue({ agents: [SUPPORT], isLoading: false });
  });

  it("is not offered to somebody who may not edit agents", () => {
    can.mockReturnValue(false);
    renderIt();
    expect(screen.queryByRole("button", { name: "Add to an agent" })).toBeNull();
  });

  it("adds the resource to the picked agent's draft and says where to publish it", async () => {
    mutateAsync.mockResolvedValue({ already: false });
    renderIt();

    await userEvent.click(screen.getByRole("button", { name: "Add to an agent" }));
    await userEvent.click(screen.getByRole("button", { name: /Support/ }));

    expect(mutateAsync).toHaveBeenCalledWith({
      agentId: "a1",
      resource: { kind: "skill", id: "s1" },
    });
    const [message, options] = vi.mocked(toast.success).mock.calls[0]!;
    expect(message).toBe("refunds added to Support's draft.");
    const action = options?.action as { onClick: () => void } | undefined;
    action?.onClick();
    expect(push).toHaveBeenCalledWith("/agents/a1");
  });

  it("says so when the agent already has it", async () => {
    mutateAsync.mockResolvedValue({ already: true });
    renderIt();

    await userEvent.click(screen.getByRole("button", { name: "Add to an agent" }));
    await userEvent.click(screen.getByRole("button", { name: /Support/ }));

    expect(toast.info).toHaveBeenCalledWith("Support already has refunds.", expect.anything());
  });

  it("keeps the list open after a refusal, which the mutation has already said", async () => {
    mutateAsync.mockRejectedValue(new Error("refused"));
    renderIt();

    await userEvent.click(screen.getByRole("button", { name: "Add to an agent" }));
    await userEvent.click(screen.getByRole("button", { name: /Support/ }));

    expect(toast.success).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /Support/ })).toBeVisible();
  });

  it("offers to create an agent when there is none", async () => {
    agents.mockReturnValue({ agents: [], isLoading: false });
    renderIt();

    await userEvent.click(screen.getByRole("button", { name: "Add to an agent" }));
    await userEvent.click(screen.getByRole("button", { name: "Create an agent" }));

    expect(push).toHaveBeenCalledWith("/agents");
  });

  it("says it is loading the agents", async () => {
    agents.mockReturnValue({ agents: [], isLoading: true });
    renderIt();

    await userEvent.click(screen.getByRole("button", { name: "Add to an agent" }));

    expect(screen.getByText("Loading agents…")).toBeInTheDocument();
  });
});
