import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ASSISTANT_SLUG, ASSISTANT_TEMPLATE, AssistantButton } from "./assistant-button";
import { useAgentSelectionStore, useConversationStore } from "@/stores";

const push = vi.fn();
const install = vi.fn();
let agents: { id: string; slug: string; status: string }[] = [];
let held: string[] = [];
let installed: ((result: { agent_id: string }) => void) | undefined;

vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/hooks", () => ({
  useAgents: () => ({ agents }),
  usePermissions: () => ({ can: (perm: string) => held.includes(perm) }),
}));
vi.mock("@/hooks/use-agent-templates", () => ({
  useAgentTemplates: (_enabled: boolean, onInstalled: (result: { agent_id: string }) => void) => {
    installed = onInstalled;
    return { install, isInstalling: false };
  },
}));

async function openPopover() {
  render(<AssistantButton />);
  await userEvent.click(screen.getByRole("button", { name: "Platform assistant" }));
}

describe("AssistantButton", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    agents = [];
    held = [];
  });

  it("opens a new conversation with a published assistant", async () => {
    agents = [{ id: "a1", slug: ASSISTANT_SLUG, status: "published" }];
    useConversationStore.setState({ currentConversationId: "old" });
    await openPopover();

    await userEvent.click(await screen.findByRole("button", { name: "Open the assistant" }));

    expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a1");
    expect(useConversationStore.getState().currentConversationId).toBeNull();
    expect(push).toHaveBeenCalledWith("/chat");
  });

  it("sends a builder to finish a draft assistant", async () => {
    agents = [{ id: "a1", slug: ASSISTANT_SLUG, status: "draft" }];
    held = ["agents:edit"];
    await openPopover();

    await userEvent.click(await screen.findByRole("button", { name: "Finish setting it up" }));

    expect(push).toHaveBeenCalledWith("/agents/a1");
  });

  it("installs it from the template for a builder, then opens what was installed", async () => {
    held = ["agents:edit"];
    await openPopover();

    await userEvent.click(await screen.findByRole("button", { name: "Set up the assistant" }));
    installed?.({ agent_id: "a9" });

    expect(install).toHaveBeenCalledWith(ASSISTANT_TEMPLATE);
    expect(push).toHaveBeenCalledWith("/agents/a9");
  });

  it("tells somebody who cannot build it whom to ask", async () => {
    agents = [{ id: "a1", slug: ASSISTANT_SLUG, status: "draft" }];
    await openPopover();

    expect(await screen.findByText(/Ask an administrator/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Finish setting it up" })).not.toBeInTheDocument();
  });
});
