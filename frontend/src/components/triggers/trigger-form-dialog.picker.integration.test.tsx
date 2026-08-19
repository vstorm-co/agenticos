import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TriggerFormDialog } from "./trigger-form-dialog";
import { apiClient } from "@/lib/api-client";
import { useAgentSelectionStore } from "@/stores";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function agent(id: string, name: string, status = "published", can_run = true) {
  return { id, name, status, description: null, has_avatar: false, can_run };
}

function serve() {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/agents") {
      return {
        items: [
          agent("a1", "Analyst"),
          agent("a2", "Nightly"),
          agent("a3", "Draft", "draft"),
          agent("a4", "Restricted", "published", false),
        ],
        total: 4,
      };
    }
    // Any picked agent's environments and triggers.
    return { items: [], total: 0 };
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  useAgentSelectionStore.getState().setDefault(null);
  serve();
});

/**
 * The dialog's own agent picker - the mode behind the chat sidebar's New
 * schedule/trigger, where no agent is in context.
 */
describe("TriggerFormDialog with no agent in context", () => {
  it("seeds the picker with the user's starred default agent", async () => {
    useAgentSelectionStore.getState().setDefault("a2");
    render(<TriggerFormDialog agentId={null} open onOpenChange={vi.fn()} />, { wrapper });

    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByRole("combobox", { name: "Agent" })).toHaveTextContent(
      "Nightly",
    );
  });

  it("falls back to the first published agent when nothing is starred", async () => {
    render(<TriggerFormDialog agentId={null} open onOpenChange={vi.fn()} />, { wrapper });

    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByRole("combobox", { name: "Agent" })).toHaveTextContent(
      "Analyst",
    );
  });

  it("creates the schedule on whichever agent was picked", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.post).mockResolvedValue({});
    render(<TriggerFormDialog agentId={null} open onOpenChange={vi.fn()} />, { wrapper });

    const dialog = await screen.findByRole("dialog");
    await user.click(await within(dialog).findByRole("combobox", { name: "Agent" }));
    // Only published agents are offered - a draft has no version to run.
    expect(screen.queryByRole("option", { name: "Draft" })).toBeNull();
    // Nor an agent the caller cannot run, published or not - the picker never
    // offers a target the create would refuse.
    expect(screen.queryByRole("option", { name: "Restricted" })).toBeNull();
    await user.click(await screen.findByRole("option", { name: "Nightly" }));
    await user.type(within(dialog).getByLabelText("Message"), "Do it");
    await user.click(within(dialog).getByRole("button", { name: "Continue" }));
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(apiClient.post).toHaveBeenCalledWith(
      "/agents/a2/triggers",
      expect.objectContaining({ prompt: "Do it", trigger_type: "schedule" }),
    );
  });
});
