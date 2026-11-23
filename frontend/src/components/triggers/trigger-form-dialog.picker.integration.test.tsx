import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TriggerFormDialog } from "./trigger-form-dialog";
import { apiClient } from "@/lib/api-client";
import { useAgentSelectionStore, useAuthStore } from "@/stores";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
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
    if (path.endsWith("/sources"))
      return {
        current: true,
        review_token: "sources",
        version_id: "v1",
        resources: ["Skill instructions"],
        accounts: [],
        unavailable_sources: [],
      };
    if (path.endsWith("/action-consents"))
      return { can_waive: true, review_token: "actions", items: [] };
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
    vi.mocked(apiClient.post).mockResolvedValue({
      id: "t-1",
      agent_id: "a2",
      trigger_type: "schedule",
    });
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
    await user.type(within(dialog).getByLabelText("Message"), "Do it");
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

it("defaults a routine proposed in a chat to shared history", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.post).mockResolvedValue({
    id: "t-chat",
    agent_id: "a1",
    trigger_type: "schedule",
  });
  render(<TriggerFormDialog agentId="a1" open onOpenChange={vi.fn()} />, { wrapper });
  const dialog = await screen.findByRole("dialog");
  await user.type(within(dialog).getByLabelText("Message"), "Report here");
  await user.click(within(dialog).getByRole("button", { name: "Create" }));
  expect(apiClient.post).toHaveBeenCalledWith(
    "/agents/a1/triggers",
    expect.objectContaining({
      chat_mode: "shared",
    }),
  );
});

it("creates a quiet Inbox routine with working chats instead of a report destination", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.post).mockResolvedValue({ id: "t-inbox", trigger_type: "schedule" });
  render(<TriggerFormDialog agentId="a1" open onOpenChange={vi.fn()} />, { wrapper });
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).queryByRole("combobox", { name: "When to bring results" })).toBeNull();
  await user.type(
    within(dialog).getByLabelText("Message"),
    "Check new mail and prepare drafts without sending.",
  );
  await user.click(within(dialog).getByRole("button", { name: "Create" }));
  expect(apiClient.post).toHaveBeenCalledWith(
    "/agents/a1/triggers",
    expect.objectContaining({
      action_mode: "agent",
      prompt: "Check new mail and prepare drafts without sending.",
    }),
  );
});

it("creates paused and saves reviewed sources and actions before enabling", async () => {
  const user = userEvent.setup();
  const closed = vi.fn();
  const normal = vi.mocked(apiClient.get).getMockImplementation()!;
  vi.mocked(apiClient.get).mockImplementation(async (path, options) => {
    if (path.endsWith("/sources"))
      return {
        current: false,
        review_token: "exact-sources",
        version_id: "v1",
        resources: ["Glossary skill"],
        accounts: [],
        unavailable_sources: [],
      };
    if (path.endsWith("/action-consents"))
      return {
        can_waive: true,
        review_token: "exact-actions",
        items: [
          {
            capability_id: "sandbox",
            tool_id: "execute",
            name: "execute",
            consented: false,
            waivable: true,
          },
        ],
      };
    return normal(path, options);
  });
  vi.mocked(apiClient.post).mockResolvedValue({
    id: "new",
    agent_id: "a1",
    trigger_type: "schedule",
    is_active: false,
  });
  vi.mocked(apiClient.put).mockImplementation(async (path) =>
    path.endsWith("/sources")
      ? {
          current: true,
          review_token: "exact-sources",
          version_id: "v1",
          resources: ["Glossary skill"],
          accounts: [],
          unavailable_sources: [],
        }
      : { can_waive: true, review_token: "exact-actions", items: [] },
  );
  vi.mocked(apiClient.patch).mockResolvedValue({
    id: "new",
    agent_id: "a1",
    trigger_type: "schedule",
    is_active: true,
  });
  render(<TriggerFormDialog agentId="a1" open onOpenChange={closed} />, { wrapper });
  let dialog = within(await screen.findByRole("dialog"));
  await user.click(dialog.getByText("Advanced options"));
  await user.click(dialog.getByRole("checkbox", { name: /Review access before enabling/ }));
  await user.type(dialog.getByLabelText("Message"), "Check the glossary");
  await user.click(dialog.getByRole("button", { name: "Create" }));
  dialog = within(await screen.findByRole("dialog", { name: "Review routine access" }));
  expect(await dialog.findByText("Glossary skill")).toBeVisible();
  expect(closed).not.toHaveBeenCalled();
  expect(apiClient.patch).not.toHaveBeenCalled();
  expect(apiClient.post).toHaveBeenCalledWith(
    "/agents/a1/triggers",
    expect.objectContaining({ is_active: false }),
  );
  await user.click(await dialog.findByRole("checkbox", { name: "execute" }));
  await user.click(dialog.getByRole("button", { name: "Enable routine" }));
  expect(apiClient.put).toHaveBeenNthCalledWith(1, "/agents/a1/triggers/new/sources", {
    review_token: "exact-sources",
    mode: "restricted",
  });
  expect(apiClient.put).toHaveBeenNthCalledWith(2, "/agents/a1/triggers/new/action-consents", {
    actions: [{ capability_id: "sandbox", tool_id: "execute" }],
    review_token: "exact-actions",
  });
  expect(apiClient.patch).toHaveBeenCalledWith("/agents/a1/triggers/new", { is_active: true });
  expect(closed).toHaveBeenCalledWith(false);
});

it("creates with agent source access without a mandatory approval modal", async () => {
  const user = userEvent.setup();
  const closed = vi.fn();
  vi.mocked(apiClient.post).mockResolvedValue({
    id: "new",
    agent_id: "a1",
    trigger_type: "schedule",
    is_active: true,
  });
  render(<TriggerFormDialog agentId="a1" open onOpenChange={closed} />, { wrapper });
  const dialog = within(await screen.findByRole("dialog"));
  await user.type(dialog.getByLabelText("Message"), "Check the glossary");
  await user.click(dialog.getByRole("button", { name: "Create" }));
  await waitFor(() => expect(closed).toHaveBeenCalledWith(false));
  expect(apiClient.post).toHaveBeenCalledWith(
    "/agents/a1/triggers",
    expect.objectContaining({ source_mode: "follow_agent" }),
  );
  const request = vi.mocked(apiClient.post).mock.calls[0]?.[1];
  expect(request).not.toHaveProperty("is_active");
  expect(request).not.toHaveProperty("review_before_activation");
  expect(screen.queryByRole("dialog", { name: "Review routine access" })).not.toBeInTheDocument();
  expect(apiClient.put).not.toHaveBeenCalled();
});

it.each([
  { signedIn: true, permission: true, impersonated: false, enabled: true },
  { signedIn: true, permission: false, impersonated: false, enabled: true },
  { signedIn: false, permission: true, impersonated: false, enabled: false },
  { signedIn: true, permission: true, impersonated: true, enabled: false },
])(
  "defaults creator access to the signed-in person independent of role permissions: %j",
  async ({ signedIn, permission, impersonated, enabled }) => {
    const previous = useAuthStore.getState().user;
    useAuthStore.setState({
      user: signedIn
        ? {
            id: "owner",
            email: "owner@example.com",
            is_active: true,
            created_at: "2026-11-21T00:00:00Z",
            impersonation: impersonated
              ? {
                  session_id: "session",
                  impersonator: { id: "admin", email: "admin@example.com" },
                  expires_at: "2026-11-22T00:00:00Z",
                }
              : null,
          }
        : null,
    });
    const normal = vi.mocked(apiClient.get).getMockImplementation()!;
    vi.mocked(apiClient.get).mockImplementation(async (path, options) =>
      path === "/me/permissions"
        ? {
            role: permission ? "owner" : "viewer",
            permissions: permission ? [{ permission: "personal:consent", scope: "all" }] : [],
          }
        : normal(path, options),
    );
    const user = userEvent.setup();
    const view = render(<TriggerFormDialog agentId="a1" open onOpenChange={vi.fn()} />, {
      wrapper,
    });
    const dialog = within(await screen.findByRole("dialog"));
    await user.click(dialog.getByText("Advanced options"));
    const identity = dialog.getByRole("checkbox", {
      name: /Run as me|Runs as the person who made it/,
    });
    await waitFor(() =>
      enabled ? expect(identity).toBeChecked() : expect(identity).not.toBeChecked(),
    );
    if (enabled) {
      expect(
        dialog.getByText("Runs as you. Your permissions and required approvals still apply."),
      ).toBeVisible();
      expect(identity).toBeEnabled();
      await user.click(identity);
      expect(identity).not.toBeChecked();
      await user.click(identity);
      expect(identity).toBeChecked();
      await user.click(identity);
      expect(identity).not.toBeChecked();
      await user.click(dialog.getByText("Advanced options"));
      await user.click(dialog.getByText("Advanced options"));
      expect(dialog.getByRole("checkbox", { name: /Run as me/ })).not.toBeChecked();
    } else expect(identity).toBeDisabled();
    view.unmount();
    useAuthStore.setState({ user: previous });
  },
);

it("creates a manual-approval routine from one form without changing its source access", async () => {
  const previous = useAuthStore.getState().user;
  useAuthStore.setState({
    user: {
      id: "owner",
      email: "owner@example.com",
      is_active: true,
      created_at: "2026-11-23T00:00:00Z",
    },
  });
  const user = userEvent.setup();
  vi.mocked(apiClient.post).mockResolvedValue({
    id: "manual",
    agent_id: "a1",
    trigger_type: "schedule",
  });
  const view = render(<TriggerFormDialog agentId="a1" open onOpenChange={vi.fn()} />, { wrapper });
  const dialog = within(await screen.findByRole("dialog"));
  expect(dialog.queryByRole("button", { name: "Continue" })).toBeNull();
  expect(dialog.getByLabelText("Message")).toBeVisible();
  await user.type(
    dialog.getByLabelText("Message"),
    "Prepare my weekly report and ask before actions.",
  );
  await user.click(dialog.getByRole("combobox", { name: "Tool approvals" }));
  await user.click(await screen.findByRole("option", { name: "Ask before actions" }));
  await user.click(dialog.getByRole("button", { name: "Create" }));
  await waitFor(() =>
    expect(apiClient.post).toHaveBeenCalledWith(
      "/agents/a1/triggers",
      expect.objectContaining({
        action_mode: "manual",
        source_mode: "follow_agent",
        runs_as_creator: true,
      }),
    ),
  );
  view.unmount();
  useAuthStore.setState({ user: previous });
});
