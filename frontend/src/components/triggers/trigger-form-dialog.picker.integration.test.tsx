import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
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
  return {
    id,
    slug: name.toLowerCase().replaceAll(" ", "-"),
    name,
    status,
    description: null,
    has_avatar: false,
    can_run,
  };
}

function serve() {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/me/permissions") return { permissions: [] };
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
    vi.mocked(apiClient.post).mockResolvedValue({ id: "t-1", trigger_type: "schedule" });
    const onCreated = vi.fn();
    render(<TriggerFormDialog agentId={null} open onOpenChange={vi.fn()} onCreated={onCreated} />, {
      wrapper,
    });

    const dialog = await screen.findByRole("dialog");
    await user.click(await within(dialog).findByRole("combobox", { name: "Agent" }));
    // Only published agents are offered - a draft has no version to run.
    expect(screen.queryByRole("option", { name: /Draft/ })).toBeNull();
    // Nor an agent the caller cannot run, published or not - the picker never
    // offers a target the create would refuse.
    expect(screen.queryByRole("option", { name: /Restricted/ })).toBeNull();
    await user.click(await screen.findByRole("option", { name: /Nightly/ }));
    await user.click(
      within(dialog).getByRole("combobox", { name: "Pause after repeated failures" }),
    );
    await user.click(
      await screen.findByRole("option", { name: "Do not pause for repeated execution failures" }),
    );
    fireEvent.change(within(dialog).getByLabelText("Ends at (device time)"), {
      target: { value: "2099-01-01T12:00" },
    });
    await user.click(within(dialog).getByRole("button", { name: "Continue" }));
    await user.type(within(dialog).getByLabelText("Message"), "Do it");
    await user.click(within(dialog).getByRole("button", { name: "Continue" }));
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(apiClient.post).toHaveBeenCalledWith(
      "/agents/a2/triggers",
      expect.objectContaining({
        prompt: "Do it",
        trigger_type: "schedule",
        max_failures: null,
        ends_at: new Date("2099-01-01T12:00").toISOString(),
      }),
    );
    // The caller learns the routine exists - a suggestion is taken only then.
    expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ id: "t-1" }));
  });
});

it("delivers a routine proposed in a chat back to that exact chat", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.post).mockResolvedValue({ id: "t-chat", trigger_type: "schedule" });
  render(
    <TriggerFormDialog
      agentId="a1"
      originConversationId="source-chat"
      open
      onOpenChange={vi.fn()}
    />,
    { wrapper },
  );
  const dialog = await screen.findByRole("dialog");
  await user.click(within(dialog).getByRole("button", { name: "Continue" }));
  await user.type(within(dialog).getByLabelText("Message"), "Report here");
  await user.click(within(dialog).getByRole("button", { name: "Continue" }));
  await user.click(within(dialog).getByRole("button", { name: "Create" }));
  expect(apiClient.post).toHaveBeenCalledWith(
    "/agents/a1/triggers",
    expect.objectContaining({
      answer_to: "conversation",
      delivery_conversation_id: "source-chat",
    }),
  );
});

it("creates a quiet Inbox routine with working chats instead of a report destination", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.post).mockResolvedValue({ id: "t-inbox", trigger_type: "schedule" });
  render(<TriggerFormDialog agentId="a1" open onOpenChange={vi.fn()} />, { wrapper });
  const dialog = await screen.findByRole("dialog");
  await user.click(within(dialog).getByRole("combobox", { name: "When to bring results" }));
  await user.click(
    await screen.findByRole("option", { name: "Only when something needs attention" }),
  );
  expect(within(dialog).queryByRole("combobox", { name: "Where the answer goes" })).toBeNull();
  await user.click(within(dialog).getByRole("button", { name: "Continue" }));
  await user.type(
    within(dialog).getByLabelText("Message"),
    "Check new mail and prepare drafts without sending.",
  );
  await user.click(within(dialog).getByRole("button", { name: "Continue" }));
  await user.click(within(dialog).getByRole("button", { name: "Create" }));
  expect(apiClient.post).toHaveBeenCalledWith(
    "/agents/a1/triggers",
    expect.objectContaining({ result_mode: "inbox" }),
  );
});
