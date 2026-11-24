import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { useAuthStore, useOrgStore } from "@/stores";
import type {
  NetworkConnection,
  NetworkConnectionList,
  NetworkEnrollment,
} from "@/types/network-connections";
import { NetworkConnections } from "./network-connections";

const permissionState = vi.hoisted(() => ({ manageScope: "shared" }));
vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn(), patch: vi.fn() },
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    isLoaded: true,
    can: (permission: string) =>
      permission === "networks:view" ||
      (permission === "networks:manage" && permissionState.manageScope !== "none"),
    scopeOf: () => permissionState.manageScope as "none" | "own" | "shared" | "team" | "all",
  }),
}));

const USER_ID = "user-1";
const ORG_ID = "org-1";
const CONNECTION_ID = "network-1";
const LOGIN_URL = "https://login.tailscale.com/a/c-test-sign-in";

function connection(overrides: Partial<NetworkConnection> = {}): NetworkConnection {
  return {
    id: CONNECTION_ID,
    organization_id: ORG_ID,
    owner_user_id: USER_ID,
    scope: "user",
    name: "Home tailnet",
    desired_state: "paused",
    auth_state: "not_connected",
    runtime_state: "stopped",
    cleanup_state: "none",
    tailnet_name: null,
    node_id: null,
    last_seen_at: null,
    last_error_code: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    can_manage: true,
    ...overrides,
  };
}

let listItems: NetworkConnection[];
let total: number;
let available: boolean;
let detail: NetworkConnection;
let enrollmentExpiresAt: string;
let pendingEnrollmentPoll: boolean;
let enrollmentCalls: number;
let enrollmentSignals: AbortSignal[];

function mount() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  const result = render(
    <QueryClientProvider client={client}>
      <NetworkConnections />
    </QueryClientProvider>,
  );
  return { client, ...result };
}

beforeEach(() => {
  vi.clearAllMocks();
  permissionState.manageScope = "shared";
  window.history.replaceState(null, "", "/connectors");
  useAuthStore.setState({
    user: {
      id: USER_ID,
      email: "one@example.test",
      is_active: true,
      created_at: "2026-01-01",
    },
  });
  useOrgStore.setState({ activeOrgId: ORG_ID });
  listItems = [connection()];
  total = listItems.length;
  available = true;
  detail = connection();
  enrollmentExpiresAt = new Date(Date.now() + 60_000).toISOString();
  pendingEnrollmentPoll = false;
  enrollmentCalls = 0;
  enrollmentSignals = [];

  vi.mocked(apiClient.get).mockImplementation(async (url, options) => {
    const params = (options as { params?: { skip?: string; limit?: string } } | undefined)?.params;
    if (url === "/network-connections") {
      const skip = Number(params?.skip ?? 0);
      const limit = Number(params?.limit ?? 50);
      const result: NetworkConnectionList = {
        items: listItems.slice(skip, skip + limit),
        total,
        available,
      };
      return result;
    }
    if (url.endsWith("/enrollment")) {
      const signal = (options as { signal?: AbortSignal } | undefined)?.signal;
      if (signal) enrollmentSignals.push(signal);
      enrollmentCalls += 1;
      if (pendingEnrollmentPoll && enrollmentCalls > 1) {
        const stopped: NetworkEnrollment = {
          attempt_id: null,
          expires_at: null,
          login_url: null,
        };
        if (signal) {
          return new Promise<NetworkEnrollment>((resolve) => {
            signal.addEventListener("abort", () => resolve(stopped), { once: true });
          });
        }
        return stopped;
      }
      return {
        attempt_id: "attempt-1",
        expires_at: enrollmentExpiresAt,
        login_url: LOGIN_URL,
      } satisfies NetworkEnrollment;
    }
    if (url.endsWith("/peers")) return { items: [], observed_at: null };
    if (url === `/network-connections/${CONNECTION_ID}`) return detail;
    throw new Error(`Unexpected GET ${url}`);
  });

  vi.mocked(apiClient.post).mockImplementation(async (url, body) => {
    if (url === "/network-connections") {
      const input = body as { name: string; scope: "user" | "org" };
      const created = connection({
        id: `created-${listItems.length + 1}`,
        owner_user_id: input.scope === "user" ? USER_ID : null,
        name: input.name,
        scope: input.scope,
      });
      listItems = [created, ...listItems];
      total += 1;
      return created;
    }
    if (url === `/network-connections/${CONNECTION_ID}/connect`) {
      detail = connection({
        desired_state: "active",
        auth_state: "sign_in_required",
        runtime_state: "starting",
      });
      return detail;
    }
    throw new Error(`Unexpected POST ${url}`);
  });
});

describe("Devices & networks boundary", () => {
  it("lists without starting enrollment and offers Connect for a fresh paused record", async () => {
    mount();

    expect(await screen.findByText("Home tailnet")).toBeVisible();
    expect(screen.getByRole("button", { name: "Connect device" })).toBeEnabled();
    expect(apiClient.get).toHaveBeenCalledWith(
      "/network-connections",
      expect.objectContaining({ params: { skip: "0", limit: "50" } }),
    );
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("keeps the explicit sign-in URL in transient UI state and aborts it on close", async () => {
    const user = userEvent.setup();
    const { client } = mount();

    await user.click(await screen.findByRole("button", { name: "Connect device" }));
    expect(apiClient.post).toHaveBeenCalledWith(`/network-connections/${CONNECTION_ID}/connect`);
    const loginLink = await screen.findByRole("link", { name: "Open Tailscale sign-in" });
    expect(loginLink).toHaveAttribute("href", LOGIN_URL);

    const serializedCache = client
      .getQueryCache()
      .getAll()
      .map((query) => JSON.stringify(query.state.data))
      .join("\n");
    expect(serializedCache).not.toContain(LOGIN_URL);

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(enrollmentSignals[0]?.aborted).toBe(true);
  });

  it.each(["organization", "account"] as const)(
    "clears and aborts the private sign-in URL when the %s scope changes",
    async (scopeChange) => {
      const user = userEvent.setup();
      mount();
      await user.click(await screen.findByRole("button", { name: "Connect device" }));
      expect(await screen.findByRole("link", { name: "Open Tailscale sign-in" })).toBeVisible();

      act(() => {
        if (scopeChange === "organization") {
          useOrgStore.setState({ activeOrgId: "org-2" });
        } else {
          const current = useAuthStore.getState().user!;
          useAuthStore.setState({ user: { ...current, id: "user-2" } });
        }
      });

      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      expect(enrollmentSignals[0]?.aborted).toBe(true);
      expect(screen.queryByRole("link", { name: "Open Tailscale sign-in" })).toBeNull();
    },
  );

  it("expires the URL and aborts a poll that is still pending at the deadline", async () => {
    const user = userEvent.setup();
    enrollmentExpiresAt = new Date(Date.now() + 2_600).toISOString();
    pendingEnrollmentPoll = true;
    mount();

    await user.click(await screen.findByRole("button", { name: "Connect device" }));
    expect(await screen.findByRole("link", { name: "Open Tailscale sign-in" })).toBeVisible();
    await waitFor(() => expect(enrollmentCalls).toBeGreaterThan(1), { timeout: 4_000 });
    await waitFor(
      () => expect(screen.queryByRole("link", { name: "Open Tailscale sign-in" })).toBeNull(),
      { timeout: 4_000 },
    );
    expect(enrollmentSignals[enrollmentSignals.length - 1]?.aborted).toBe(true);
  });

  it("lets a shared manager create personal and organization records without enrolling", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: "Add Tailscale" }));
    await user.type(screen.getByLabelText("Connection name"), "Personal tunnel");
    await user.click(screen.getByRole("button", { name: "Create connection" }));

    await user.click(await screen.findByRole("button", { name: "Add Tailscale" }));
    await user.type(screen.getByLabelText("Connection name"), "Team tunnel");
    await user.selectOptions(screen.getByLabelText("Ownership"), "org");
    await user.click(screen.getByRole("button", { name: "Create connection" }));

    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(2));
    expect(apiClient.post).toHaveBeenNthCalledWith(1, "/network-connections", {
      name: "Personal tunnel",
      scope: "user",
    });
    expect(apiClient.post).toHaveBeenNthCalledWith(2, "/network-connections", {
      name: "Team tunnel",
      scope: "org",
    });
    expect(apiClient.post).not.toHaveBeenCalledWith(
      expect.stringContaining("/connect"),
      expect.anything(),
    );
  });

  it("disables Connect when the deployment is unavailable and hides management for a viewer", async () => {
    available = false;
    const { unmount } = mount();
    expect(await screen.findByText(/Tailscale runtime is not configured/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Connect device" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Add Tailscale" })).toBeNull();
    expect(apiClient.post).not.toHaveBeenCalled();

    unmount();
    permissionState.manageScope = "none";
    listItems = [connection({ can_manage: false })];
    available = true;
    mount();
    expect(await screen.findByText("View only")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Connect device" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add Tailscale" })).toBeNull();
  });

  it("paginates the list in bounded fifty-row requests", async () => {
    const user = userEvent.setup();
    listItems = Array.from({ length: 53 }, (_, index) =>
      connection({ id: `network-${index + 1}`, name: `Tailnet ${index + 1}` }),
    );
    total = listItems.length;
    mount();

    const navigation = await screen.findByRole("navigation", { name: "Network connections pages" });
    expect(within(navigation).getByText("1–50 of 53")).toBeVisible();
    await user.click(within(navigation).getByRole("button", { name: "Next" }));

    expect(await screen.findByText("Tailnet 51")).toBeVisible();
    expect(apiClient.get).toHaveBeenCalledWith(
      "/network-connections",
      expect.objectContaining({ params: { skip: "50", limit: "50" } }),
    );
  });
});
