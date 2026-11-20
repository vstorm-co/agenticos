import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { useAuthStore, useOrgStore } from "@/stores";
import { useArchitectAskStore } from "@/stores/architect-ask-store";
import type { AppConnection, ConnectedAppDefinition } from "@/types/app-connections";
import { AppConnections } from "./app-connections";

const state = vi.hoisted(() => ({ assistantReady: true }));
vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn(), patch: vi.fn() },
}));
vi.mock("@/hooks/use-assistant", () => ({
  useAssistant: () => ({
    assistant: {
      status: state.assistantReady ? "ready" : "disabled",
      agent_id: "assistant-1",
      can_use: state.assistantReady,
    },
    isLoading: false,
    error: null,
    retry: vi.fn(),
  }),
}));
const scope = { userId: "user-1", orgId: "org-1" };
const apps: ConnectedAppDefinition[] = [
  {
    key: "composio-googlecalendar",
    toolkit: "googlecalendar",
    name: "Google Calendar",
    description: "Meetings",
    category: "calendar",
    configured: true,
    availability: "ready",
    approval_required: false,
    action_count: 4,
    actions: [],
  },
  {
    key: "composio-gmail",
    toolkit: "gmail",
    name: "Gmail",
    description: "Mail",
    category: "email",
    configured: true,
    availability: "ready",
    approval_required: false,
    action_count: 6,
    actions: [],
  },
  {
    key: "composio-outlook",
    toolkit: "outlook",
    name: "Outlook",
    description: "Mail and meetings",
    category: "email",
    configured: true,
    availability: "ready",
    approval_required: false,
    action_count: 8,
    actions: [],
  },
  {
    key: "composio-linear",
    toolkit: "linear",
    name: "Linear",
    description: "Issues and projects",
    category: "developer-tools",
    configured: true,
    availability: "ready",
    approval_required: true,
    action_count: 12,
    actions: [],
  },
];
function account(overrides: Partial<AppConnection> = {}): AppConnection {
  const toolkit = overrides.toolkit ?? "googlecalendar";
  const app = apps.find((candidate) => candidate.toolkit === toolkit)!;
  return {
    id: "calendar-1",
    catalog_key: app.key,
    toolkit,
    name: app.name,
    label: "Work",
    identity: "one@example.test",
    status: "connected",
    is_enabled: true,
    is_default: true,
    authorized: true,
    readiness: "authorization_verified",
    last_checked_at: null,
    last_error: null,
    created_at: "2026-01-01",
    app,
    ...overrides,
  };
}
function data(connections: AppConnection[] = [], configured = true) {
  vi.mocked(apiClient.get).mockImplementation(async (url) =>
    url.endsWith("/catalog")
      ? {
          configured,
          catalog_available: true,
          apps: apps.map((app) => ({
            ...app,
            configured,
            availability: configured ? app.availability : "setup_required",
          })),
          next_cursor: null,
        }
      : { items: connections, total: connections.length },
  );
}
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AppConnections scope={scope} />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  window.history.replaceState(null, "", "/connectors");
  state.assistantReady = true;
  useAuthStore.setState({
    user: {
      id: scope.userId,
      email: "one@example.test",
      is_active: true,
      created_at: "2026-01-01",
    },
  });
  useOrgStore.setState({ activeOrgId: scope.orgId });
  useArchitectAskStore.setState({ request: null });
  data();
});

describe("real app connection journey", () => {
  it("explicitly re-enables a locally disabled account without starting consent", async () => {
    data([account({ is_enabled: false, status: "disabled", authorized: false })]);
    vi.mocked(apiClient.patch).mockResolvedValue(account());
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Enable" }));
    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/me/mcp-connections/calendar-1", {
        is_enabled: true,
      }),
    );
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(await screen.findByText("Account enabled.")).toBeVisible();
  });

  it("selects a goal, offers its apps, and cancels before creating any authorization", async () => {
    mount();
    await userEvent.click(await screen.findByRole("button", { name: /Review my inbox/ }));
    await userEvent.click(screen.getByRole("button", { name: "Choose apps" }));
    expect(screen.getByRole("button", { name: "Connect Google Calendar" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Connect Gmail" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/Review the exact permissions/)).toBeVisible();
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(apiClient.post).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("button", { name: /Review my inbox/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("shows every-action approval for an unapproved app before starting authorization", async () => {
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Choose apps" }));
    expect(screen.getByRole("button", { name: "Connect Linear" })).toBeVisible();
    expect(screen.getByText("Every action requires your approval")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Connect Linear" }));
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByText(/This app may support reading and making changes/),
    ).toBeVisible();
    expect(
      within(dialog).getByText(/Review the exact permissions on the provider's consent screen/),
    ).toBeVisible();
    expect(apiClient.post).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("debounces catalog search before requesting matching apps", async () => {
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Choose apps" }));
    const initialCatalogCalls = vi
      .mocked(apiClient.get)
      .mock.calls.filter(([url]) => url.endsWith("/catalog")).length;
    fireEvent.change(screen.getByPlaceholderText("Search all apps"), {
      target: { value: "linear" },
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 100));
    });
    expect(
      vi.mocked(apiClient.get).mock.calls.filter(([url]) => url.endsWith("/catalog")),
    ).toHaveLength(initialCatalogCalls);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 250));
    });
    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith(
        "/me/app-connections/catalog",
        expect.objectContaining({ params: { limit: "24", search: "linear" } }),
      ),
    );
  });

  it("loads the next catalog page from the visible load-more control", async () => {
    let catalogCalls = 0;
    vi.mocked(apiClient.get).mockImplementation(async (url) => {
      if (!url.endsWith("/catalog")) return { items: [], total: 0 };
      catalogCalls += 1;
      return catalogCalls === 1
        ? {
            configured: true,
            catalog_available: true,
            apps: [apps[0]],
            next_cursor: "catalog-page-2",
          }
        : {
            configured: true,
            catalog_available: true,
            apps: [apps[1]],
            next_cursor: null,
          };
    });
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Choose apps" }));
    expect(screen.getByRole("button", { name: "Connect Google Calendar" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Connect Gmail" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Load more apps" }));
    expect(await screen.findByRole("button", { name: "Connect Gmail" })).toBeVisible();
    expect(apiClient.get).toHaveBeenCalledWith(
      "/me/app-connections/catalog",
      expect.objectContaining({
        params: expect.objectContaining({ cursor: "catalog-page-2" }),
      }),
    );
  });

  it("keeps existing accounts usable when the catalog request fails", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (url) => {
      if (url.endsWith("/catalog")) throw new Error("catalog unavailable");
      return { items: [account()], total: 1 };
    });
    mount();
    expect(await screen.findByText("Google Calendar")).toBeVisible();
    expect(screen.getByRole("region", { name: "Your connected accounts" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Choose apps" }));
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  });

  it("offers an explore prompt for a usable app outside the selected goal", async () => {
    data([
      account({
        id: "linear-1",
        catalog_key: "composio-linear",
        toolkit: "linear",
        name: "Linear",
        identity: "team@example.test",
      }),
    ]);
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Skip for now" }));
    const exploreButton = screen.getByRole("button", {
      name: "Explore this app with my assistant",
    });
    expect(exploreButton).toBeVisible();
    await userEvent.click(exploreButton);
    expect(useArchitectAskStore.getState().request?.text).toContain("connected linear account");
    expect(useArchitectAskStore.getState().request?.text).toContain(
      "Do not call app tools until I choose a task.",
    );
  });

  it("shows deployment configuration truth and prevents unconfigured authorization", async () => {
    data([], false);
    mount();
    expect(await screen.findByText("App connections are not configured yet")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Choose apps" }));
    expect(screen.getByRole("button", { name: "Connect Google Calendar" })).toBeDisabled();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("does not present a sample result or runnable task for an unverified account", async () => {
    data([account({ status: "pending", authorized: false, readiness: "authorization_required" })]);
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Skip for now" }));
    expect(screen.getByText(/Connect and verify an app for this task first/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Prepare my day" })).toBeNull();
    expect(screen.getByRole("link", { name: "Continue without apps" })).toHaveAttribute(
      "href",
      "/chat",
    );
    expect(useArchitectAskStore.getState().request).toBeNull();
  });

  it("sends a real, read-only request for the selected account with user and workspace scope", async () => {
    data([
      account(),
      account({
        id: "calendar-2",
        identity: "two@example.test",
        label: "Personal",
        is_default: false,
      }),
    ]);
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Skip for now" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Use this account" }), {
      target: { value: "calendar-2" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Prepare my day" }));
    const request = useArchitectAskStore.getState().request;
    expect(request?.scope).toEqual(scope);
    expect(request?.text).toContain("two@example.test");
    expect(request?.text).toContain("connection calendar-2");
    expect(request?.text).toContain("Read only");
    expect(request?.text).not.toContain("one@example.test");
    expect(screen.getByText(/Request sent to your assistant/)).toBeVisible();
  });

  it("does not offer a task when the assistant is disabled", async () => {
    data([account()]);
    state.assistantReady = false;
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Skip for now" }));
    expect(screen.getByText(/Your assistant is not ready/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Prepare my day" })).toBeNull();
  });

  it("continues a chat-requested Gmail setup with a compatible first task", async () => {
    window.history.replaceState(null, "", "/connectors?app=gmail");
    data([
      account({ id: "gmail-1", toolkit: "gmail", catalog_key: "composio-gmail", name: "Gmail" }),
    ]);
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Continue" }));
    await userEvent.click(screen.getByRole("button", { name: "Review my inbox" }));
    expect(useArchitectAskStore.getState().request?.text).toContain("connection gmail-1");
  });

  it("distinguishes labeled accounts with the same provider identity", async () => {
    data([account(), account({ id: "calendar-2", label: "Personal", is_default: false })]);
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Skip for now" }));
    expect(
      screen.getByRole("option", { name: "Work · one@example.test · googlecalendar" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "Personal · one@example.test · googlecalendar" }),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "calendar-2" } });
    await userEvent.click(screen.getByRole("button", { name: "Prepare my day" }));
    expect(useArchitectAskStore.getState().request?.text).toContain("Personal · one@example.test");
    expect(useArchitectAskStore.getState().request?.text).toContain("connection calendar-2");
  });

  it("verifies identity-only callbacks on the server and clears sensitive return parameters", async () => {
    window.history.replaceState(
      null,
      "",
      "/connectors?session_uri=identity-session&status=success",
    );
    vi.mocked(apiClient.post).mockResolvedValue(account());
    data([account()]);
    mount();
    expect(await screen.findByText("Your app authorization was verified.")).toBeVisible();
    expect(apiClient.post).toHaveBeenCalledWith("/me/app-connections/callback", {
      session_uri: "identity-session",
    });
    expect(window.location.search).toBe("");
  });

  it("does not turn a pending callback or forged success query into verified access", async () => {
    window.history.replaceState(null, "", "/connectors?connection_attempt=attempt&status=success");
    vi.mocked(apiClient.post).mockResolvedValue(
      account({ status: "pending", authorized: false, readiness: "unavailable" }),
    );
    mount();
    expect(await screen.findByText(/Authorization is not ready yet/)).toBeVisible();
    expect(screen.queryByText("Your app authorization was verified.")).toBeNull();
  });

  it("keeps a failed verification retryable without trusting the callback string", async () => {
    window.history.replaceState(null, "", "/connectors?session_uri=identity-session");
    vi.mocked(apiClient.post)
      .mockRejectedValueOnce(new Error("temporarily unavailable"))
      .mockResolvedValueOnce(account());
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Verify again" }));
    expect(await screen.findByText("Your app authorization was verified.")).toBeVisible();
    expect(apiClient.post).toHaveBeenCalledTimes(2);
  });

  it("keeps authorization errors visible and never follows an unsafe redirect", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ redirect_url: "javascript:alert(1)" });
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Choose apps" }));
    await userEvent.click(screen.getByRole("button", { name: "Connect Google Calendar" }));
    await userEvent.click(screen.getByRole("button", { name: "Continue to app" }));
    expect(await screen.findByText(/invalid authorization address/)).toBeVisible();
    expect(window.location.pathname).toBe("/connectors");
  });

  it("confirms disconnect, refreshes status, and routes reconnection to the managed endpoint", async () => {
    const expired = account({
      status: "expired",
      authorized: false,
      readiness: "authorization_required",
    });
    data([expired]);
    vi.mocked(apiClient.post).mockResolvedValue({ redirect_url: "invalid" });
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Reconnect" }));
    await userEvent.click(screen.getByRole("button", { name: "Continue to app" }));
    await screen.findByText(/invalid authorization address/);
    expect(apiClient.post).toHaveBeenCalledWith("/me/app-connections/calendar-1/reconnect", {});
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "Check access" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/me/app-connections/calendar-1/refresh", {}),
    );
    await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    expect(apiClient.delete).not.toHaveBeenCalled();
    await userEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Disconnect" }),
    );
    await waitFor(() =>
      expect(apiClient.delete).toHaveBeenCalledWith("/me/app-connections/calendar-1"),
    );
  });

  it("does not dispatch a task after its workspace changes", async () => {
    data([account()]);
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Skip for now" }));
    act(() => useOrgStore.setState({ activeOrgId: "other-org" }));
    await userEvent.click(screen.getByRole("button", { name: "Prepare my day" }));
    expect(useArchitectAskStore.getState().request).toBeNull();
  });
});
