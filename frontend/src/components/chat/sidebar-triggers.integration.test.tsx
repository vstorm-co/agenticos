import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SidebarTriggers } from "./sidebar-triggers";
import { apiClient } from "@/lib/api-client";
import type { Trigger } from "@/types/triggers";

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

function trigger(overrides: Partial<Trigger> = {}): Trigger {
  return {
    id: "t1",
    agent_id: "a1",
    agent_name: "Nightly",
    name: null,
    created_by_user_id: null,
    is_active: true,
    environment_id: null,
    trigger_type: "schedule",
    schedule_kind: "interval",
    interval_seconds: 900,
    cron_expression: null,
    event_source: null,
    event_config: {},
    prompt: "Summarise the day",
    next_fire_at: null,
    last_fired_at: null,
    last_run_id: null,
    conversation_id: null,
    webhook_url: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

function serve(triggers: Trigger[]) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/triggers") return { items: triggers, total: triggers.length };
    if (path.startsWith("/agents/")) return { items: [], total: 0 };
    throw new Error(`unexpected GET ${path}`);
  });
}

beforeEach(() => vi.clearAllMocks());

describe("SidebarTriggers", () => {
  it("fetches nothing until the section is expanded", () => {
    serve([]);
    render(<SidebarTriggers onOpenConversation={vi.fn()} canManage />, { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("lists the organization's triggers once expanded", async () => {
    const user = userEvent.setup();
    serve([trigger()]);
    render(<SidebarTriggers onOpenConversation={vi.fn()} canManage />, { wrapper });

    await user.click(screen.getByRole("button", { name: "Schedules & triggers" }));

    expect(await screen.findByText("Nightly")).toBeVisible();
    expect(screen.getByText("Every 15 minutes")).toBeVisible();
  });

  it("says the section is empty rather than showing nothing", async () => {
    const user = userEvent.setup();
    serve([]);
    render(<SidebarTriggers onOpenConversation={vi.fn()} canManage />, { wrapper });

    await user.click(screen.getByRole("button", { name: "Schedules & triggers" }));

    expect(await screen.findByText("Nothing scheduled yet.")).toBeVisible();
  });

  it("says the list failed to load rather than showing it as empty", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.get).mockRejectedValue(new Error("boom"));
    render(<SidebarTriggers onOpenConversation={vi.fn()} canManage />, { wrapper });

    await user.click(screen.getByRole("button", { name: "Schedules & triggers" }));

    expect(await screen.findByText("Could not load the list.")).toBeVisible();
  });

  it("opens the empty conversation for a trigger that has never fired", async () => {
    const user = userEvent.setup();
    const onOpenConversation = vi.fn();
    serve([trigger({ last_run_id: null, conversation_id: "c1" })]);
    render(<SidebarTriggers onOpenConversation={onOpenConversation} canManage />, { wrapper });

    await user.click(screen.getByRole("button", { name: "Schedules & triggers" }));
    await user.click(await screen.findByRole("button", { name: "Open Nightly trigger" }));

    // A run-less trigger opens its eager, empty conversation - not a config form.
    expect(onOpenConversation).toHaveBeenCalledWith("c1");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens the editor for a trigger with no conversation to show", async () => {
    const user = userEvent.setup();
    const onOpenConversation = vi.fn();
    serve([trigger({ last_run_id: null, conversation_id: null })]);
    render(<SidebarTriggers onOpenConversation={onOpenConversation} canManage />, { wrapper });

    await user.click(screen.getByRole("button", { name: "Schedules & triggers" }));
    await user.click(await screen.findByRole("button", { name: "Open Nightly trigger" }));

    // Nothing to read and nothing to open: fall back to what can be acted on.
    expect(await screen.findByRole("dialog")).toBeVisible();
    expect(onOpenConversation).not.toHaveBeenCalled();
  });

  it("opens the run-log conversation for a trigger that has fired", async () => {
    const user = userEvent.setup();
    const onOpenConversation = vi.fn();
    serve([trigger({ last_run_id: "r1", conversation_id: "c1" })]);
    render(<SidebarTriggers onOpenConversation={onOpenConversation} canManage />, { wrapper });

    await user.click(screen.getByRole("button", { name: "Schedules & triggers" }));
    await user.click(await screen.findByRole("button", { name: "Open Nightly trigger" }));

    expect(onOpenConversation).toHaveBeenCalledWith("c1");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("pauses a trigger from its row menu", async () => {
    const user = userEvent.setup();
    serve([trigger()]);
    vi.mocked(apiClient.patch).mockResolvedValue(trigger({ is_active: false }));
    render(<SidebarTriggers onOpenConversation={vi.fn()} canManage />, { wrapper });

    await user.click(screen.getByRole("button", { name: "Schedules & triggers" }));
    await user.click(await screen.findByRole("button", { name: "Actions for Nightly trigger" }));
    await user.click(await screen.findByRole("menuitem", { name: "Pause" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/agents/a1/triggers/t1", {
        is_active: false,
      }),
    );
  });

  it("fires a trigger now from its row menu", async () => {
    const user = userEvent.setup();
    serve([trigger()]);
    vi.mocked(apiClient.post).mockResolvedValue(trigger());
    render(<SidebarTriggers onOpenConversation={vi.fn()} canManage />, { wrapper });

    await user.click(screen.getByRole("button", { name: "Schedules & triggers" }));
    await user.click(await screen.findByRole("button", { name: "Actions for Nightly trigger" }));
    await user.click(await screen.findByRole("menuitem", { name: "Run now" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/agents/a1/triggers/t1/run", {}),
    );
  });

  it("removes a trigger from its row menu", async () => {
    const user = userEvent.setup();
    serve([trigger()]);
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    render(<SidebarTriggers onOpenConversation={vi.fn()} canManage />, { wrapper });

    await user.click(screen.getByRole("button", { name: "Schedules & triggers" }));
    await user.click(await screen.findByRole("button", { name: "Actions for Nightly trigger" }));
    await user.click(await screen.findByRole("menuitem", { name: "Delete" }));
    // Confirmed first - a destructive one-click from a menu is a trap.
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(apiClient.delete).toHaveBeenCalledWith("/agents/a1/triggers/t1"));
  });

  it("resumes a paused trigger, whose row offers Resume instead of Pause", async () => {
    const user = userEvent.setup();
    serve([trigger({ is_active: false })]);
    vi.mocked(apiClient.patch).mockResolvedValue(trigger({ is_active: true }));
    render(<SidebarTriggers onOpenConversation={vi.fn()} canManage />, { wrapper });

    await user.click(screen.getByRole("button", { name: "Schedules & triggers" }));
    await user.click(await screen.findByRole("button", { name: "Actions for Nightly trigger" }));
    await user.click(await screen.findByRole("menuitem", { name: "Resume" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/agents/a1/triggers/t1", {
        is_active: true,
      }),
    );
  });

  it("opens the editor from the row menu", async () => {
    const user = userEvent.setup();
    serve([trigger({ last_run_id: "r1", conversation_id: "c1" })]);
    render(<SidebarTriggers onOpenConversation={vi.fn()} canManage />, { wrapper });

    await user.click(screen.getByRole("button", { name: "Schedules & triggers" }));
    await user.click(await screen.findByRole("button", { name: "Actions for Nightly trigger" }));
    await user.click(await screen.findByRole("menuitem", { name: "Edit" }));

    // The menu is how a trigger whose click opens its conversation is edited.
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeVisible();

    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("shows a viewer the list but no row menu, and does not open an editor", async () => {
    const user = userEvent.setup();
    const onOpenConversation = vi.fn();
    serve([trigger({ last_run_id: null, conversation_id: "c1" })]);
    render(<SidebarTriggers onOpenConversation={onOpenConversation} canManage={false} />, {
      wrapper,
    });

    await user.click(screen.getByRole("button", { name: "Schedules & triggers" }));
    // The list is visible - viewing is `agents:view`.
    expect(await screen.findByText("Nightly")).toBeVisible();
    // No manage controls, but the run-log conversation is a read: a viewer
    // opens it (empty here) and still gets no editor they could not save.
    expect(screen.queryByRole("button", { name: "Actions for Nightly trigger" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Open Nightly trigger" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onOpenConversation).toHaveBeenCalledWith("c1");
  });
});
