import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ClaudeSubscriptionConnection } from "./claude-subscription-connection";
import { PersonalModelConnections } from "./personal-model-connections";
import { ApiError } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores";
import { Perm, type Permission } from "@/types/permissions";
import type { ClaudeSubscriptionStatus } from "@/types/personal-subscriptions";
import type { ModelProfile } from "@/types/providers";
import type { NewModelProfile } from "@/hooks/use-model-providers";

const scope = vi.hoisted(() => ({ tenant: "org-1" as string | null }));
vi.mock("@/hooks/use-organizations", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/use-organizations")>()),
  useTenantId: () => scope.tenant,
  useTenantGuard: () => (tenant: string | null) => tenant === scope.tenant,
}));
vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const USER = {
  id: "person-1",
  email: "demo@example.test",
  is_active: true,
  created_at: "2026-11-07T00:00:00Z",
};
const PATH = "/personal-subscriptions/claude";
const AVAILABLE: ClaudeSubscriptionStatus = {
  available: true,
  connected: false,
  state: "disconnected",
  login_id: null,
  authorization_url: null,
  expires_at: null,
  error_code: null,
};
const CONNECTED: ClaudeSubscriptionStatus = { ...AVAILABLE, connected: true, state: "connected" };
function pending(): ClaudeSubscriptionStatus {
  return {
    ...AVAILABLE,
    state: "awaiting_code",
    login_id: "login-1",
    authorization_url: "https://claude.ai/oauth/authorize?state=demo",
    expires_at: new Date(Date.now() + 600_000).toISOString(),
  };
}
const state = {
  permissions: [] as Permission[],
  connection: AVAILABLE,
  profiles: [] as ModelProfile[],
  statusFails: false,
};

beforeEach(() => {
  vi.clearAllMocks();
  scope.tenant = "org-1";
  useAuthStore.setState({ user: USER });
  state.permissions = [Perm.connectionsManage, Perm.agentsView];
  state.connection = AVAILABLE;
  state.profiles = [];
  state.statusFails = false;
  vi.mocked(apiClient.get).mockImplementation(async (path) => {
    if (path === "/me/permissions")
      return {
        organization_id: "org-1",
        permissions: state.permissions.map((permission) => ({ permission, scope: "all" })),
      };
    if (path === PATH) {
      if (state.statusFails) throw new ApiError(503, "runtime status detail");
      return state.connection;
    }
    if (path === "/providers/model-profiles")
      return { items: state.profiles, total: state.profiles.length };
    if (path === "/providers/catalog") return { items: [], total: 0 };
    throw new Error(`unexpected GET ${path}`);
  });
  vi.mocked(apiClient.post).mockImplementation(async (path, payload) => {
    if (path === `${PATH}/login`) {
      state.connection = pending();
      return state.connection;
    }
    if (path === `${PATH}/login/code`) {
      state.connection = CONNECTED;
      return { ...pending(), state: "verifying", authorization_url: null };
    }
    if (path === `${PATH}/login/cancel` || path === `${PATH}/disconnect`) {
      state.connection = AVAILABLE;
      return state.connection;
    }
    if (path === "/providers/model-profiles") {
      const profile: ModelProfile = {
        ...(payload as NewModelProfile),
        id: "native-profile",
        usage_scope: "personal",
        params: {},
        fallback_profile_ids: [],
        missing_key: false,
      };
      state.profiles = [...state.profiles, profile];
      return profile;
    }
    throw new Error(`unexpected POST ${path}`);
  });
});
afterEach(() => act(() => useAuthStore.setState({ user: null })));

function mount(ui: ReactElement = <ClaudeSubscriptionConnection />) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, ...render(ui, { wrapper }) };
}

describe("Claude subscription connection", () => {
  it("shows the real subscription option independently of API-key read permissions", async () => {
    await mount(<PersonalModelConnections />);
    expect(
      await screen.findByRole("button", { name: "Connect Claude subscription" }),
    ).toBeEnabled();
    expect(screen.getByText(/Viewing personal model connections needs/)).toBeVisible();
    expect(apiClient.get).not.toHaveBeenCalledWith("/secrets");
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("withholds private reads and controls without connections:manage", async () => {
    state.permissions = [Perm.agentsView];
    mount();
    expect(await screen.findByText(/Connecting a Claude subscription needs/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Connect Claude subscription" })).toBeNull();
    expect(apiClient.get).not.toHaveBeenCalledWith(PATH, expect.anything());
  });

  it("withholds the connection during impersonation", async () => {
    useAuthStore.setState({
      user: {
        ...USER,
        impersonation: {
          session_id: "impersonation",
          impersonator: { id: "admin", email: "admin@example.test" },
          expires_at: "2026-11-07T18:00:00Z",
        },
      },
    });
    mount();
    expect(await screen.findByText(/Sign in as yourself/)).toBeVisible();
    expect(apiClient.get).not.toHaveBeenCalledWith(PATH, expect.anything());
  });

  it("completes page-code sign-in, adds a private selectable model and retains it after disconnect", async () => {
    const { client } = mount();
    await userEvent.click(
      await screen.findByRole("button", { name: "Connect Claude subscription" }),
    );
    const link = await screen.findByRole("link", { name: "Open Claude sign-in" });
    expect(link).toHaveAttribute("href", "https://claude.ai/oauth/authorize?state=demo");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    await userEvent.type(screen.getByLabelText("Claude sign-in code"), "one-time-page-code");
    await userEvent.click(screen.getByRole("button", { name: "Complete sign-in" }));
    expect(screen.queryByDisplayValue("one-time-page-code")).toBeNull();
    expect(apiClient.post).toHaveBeenCalledWith(
      `${PATH}/login/code`,
      { login_id: "login-1", code: "one-time-page-code" },
      { signal: expect.any(AbortSignal) },
    );
    expect(await screen.findByText("Connected · personal")).toBeVisible();
    expect(client.getMutationCache().getAll()).toHaveLength(0);
    expect(
      JSON.stringify(
        client
          .getQueryCache()
          .getAll()
          .map((query) => query.state.data),
      ),
    ).not.toContain("one-time-page-code");
    for (const storage of [localStorage, sessionStorage]) {
      for (let index = 0; index < storage.length; index += 1) {
        const key = storage.key(index);
        if (key !== null) expect(storage.getItem(key)).not.toContain("one-time-page-code");
      }
    }
    await userEvent.click(screen.getByLabelText("Subscription model"));
    await userEvent.click(screen.getByRole("option", { name: "Claude Opus" }));
    await userEvent.click(screen.getByRole("button", { name: "Add subscription model" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/providers/model-profiles", {
        provider: "claude-subscription",
        model: "opus",
        secret_id: null,
        label: "Claude subscription · demo@example.test · Claude Opus",
      }),
    );
    expect(await screen.findByRole("button", { name: "Model already saved" })).toBeDisabled();
    expect(screen.getByText("Claude subscription · demo@example.test · Claude Opus")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Disconnect Claude" }));
    expect(
      await screen.findByRole("button", { name: "Connect Claude subscription" }),
    ).toBeVisible();
    expect(screen.getByText("Reconnect Claude to use these saved models.")).toBeVisible();
    expect(screen.getByText("Claude subscription · demo@example.test · Claude Opus")).toBeVisible();
    expect(screen.queryByLabelText("Subscription model")).toBeNull();
    expect(apiClient.post).toHaveBeenCalledTimes(4);
  });

  it("cancels the exact login and ignores its late successful code response", async () => {
    state.connection = pending();
    let finish: ((status: ClaudeSubscriptionStatus) => void) | undefined;
    let submittedSignal: AbortSignal | undefined;
    const original = vi.mocked(apiClient.post).getMockImplementation()!;
    vi.mocked(apiClient.post).mockImplementation((path, payload, options) => {
      if (path === `${PATH}/login/code`) {
        submittedSignal = options?.signal ?? undefined;
        return new Promise((resolve) => {
          finish = resolve;
        });
      }
      return original(path, payload, options);
    });
    const { client } = mount();
    await userEvent.type(await screen.findByLabelText("Claude sign-in code"), "cancelled-code");
    await userEvent.click(screen.getByRole("button", { name: "Complete sign-in" }));
    expect(await screen.findByText("Completing Claude sign-in…")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Cancel sign-in" }));
    expect(
      await screen.findByRole("button", { name: "Connect Claude subscription" }),
    ).toBeVisible();
    expect(submittedSignal?.aborted).toBe(true);
    expect(apiClient.post).toHaveBeenCalledWith(
      `${PATH}/login/cancel`,
      { login_id: "login-1" },
      { signal: expect.any(AbortSignal) },
    );
    await act(async () => finish?.(CONNECTED));
    expect(client.getQueryData(qk.personalSubscriptions.claude("org-1:person-1"))).toEqual(
      AVAILABLE,
    );
    expect(screen.queryByText("Connected · personal")).toBeNull();
    expect(screen.queryByDisplayValue("cancelled-code")).toBeNull();
  });

  it("clears a failed code and shows a fixed error without replaying provider output", async () => {
    state.connection = pending();
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(503, "private provider output with failed-code"),
    );
    const { client } = mount();
    await userEvent.type(await screen.findByLabelText("Claude sign-in code"), "failed-code");
    await userEvent.click(screen.getByRole("button", { name: "Complete sign-in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The sign-in request could not be completed.",
    );
    expect(screen.getByLabelText("Claude sign-in code")).toHaveValue("");
    expect(screen.queryByText(/private provider output/)).toBeNull();
    expect(client.getMutationCache().getAll()).toHaveLength(0);
  });

  it("reports a failed status read and lets the user retry without starting a login", async () => {
    state.statusFails = true;
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your Claude connection could not be checked.",
    );
    state.statusFails = false;
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(
      await screen.findByRole("button", { name: "Connect Claude subscription" }),
    ).toBeVisible();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("does not offer a provider link or code submission once sign-in expires", async () => {
    state.connection = { ...pending(), expires_at: new Date(Date.now() - 10_000).toISOString() };
    mount();
    expect(await screen.findByText(/This sign-in has expired/)).toBeVisible();
    expect(screen.queryByRole("link", { name: "Open Claude sign-in" })).toBeNull();
    expect(screen.queryByLabelText("Claude sign-in code")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Start again" }));
    expect(await screen.findByLabelText("Claude sign-in code")).toHaveValue("");
  });

  it("refuses a runtime link outside Claude's authorization page", async () => {
    state.connection = { ...pending(), authorization_url: "https://evil.example/oauth/authorize" };
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The Claude sign-in link could not be verified.",
    );
    expect(screen.queryByRole("link", { name: "Open Claude sign-in" })).toBeNull();
    expect(screen.queryByLabelText("Claude sign-in code")).toBeNull();
  });

  it("only reports unconfigured when the server explicitly says so", async () => {
    state.connection = { ...AVAILABLE, available: false };
    mount();
    expect(
      await screen.findByText("Claude subscription sign-in is not configured on this deployment."),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Connect Claude subscription" })).toBeNull();
  });

  it.each(["tenant", "person"])(
    "does not restore an old connection after the %s changes",
    async (change) => {
      let finish: ((value: ClaudeSubscriptionStatus) => void) | undefined;
      vi.mocked(apiClient.post).mockImplementation(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      );
      const { client, rerender } = mount();
      await userEvent.click(
        await screen.findByRole("button", { name: "Connect Claude subscription" }),
      );
      await waitFor(() => expect(finish).toBeDefined());
      act(() => {
        if (change === "tenant") scope.tenant = "org-2";
        else useAuthStore.setState({ user: { ...USER, id: "person-2" } });
      });
      rerender(<ClaudeSubscriptionConnection />);
      expect(
        await screen.findByRole("button", { name: "Connect Claude subscription" }),
      ).toBeEnabled();
      await act(async () => finish?.(CONNECTED));
      expect(screen.queryByText("Connected · personal")).toBeNull();
      const next = change === "tenant" ? "org-2:person-1" : "org-1:person-2";
      expect(client.getQueryData(qk.personalSubscriptions.claude(next))).toEqual(AVAILABLE);
    },
  );

  it.each(["tenant", "person"])(
    "can start again after leaving and returning to the same %s during a pending request",
    async (change) => {
      let finish: ((value: ClaudeSubscriptionStatus) => void) | undefined;
      vi.mocked(apiClient.post).mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      );
      const { client, rerender } = mount();
      await userEvent.click(
        await screen.findByRole("button", { name: "Connect Claude subscription" }),
      );
      await waitFor(() => expect(finish).toBeDefined());
      act(() => {
        if (change === "tenant") scope.tenant = "org-2";
        else useAuthStore.setState({ user: { ...USER, id: "person-2" } });
      });
      rerender(<ClaudeSubscriptionConnection />);
      expect(
        await screen.findByRole("button", { name: "Connect Claude subscription" }),
      ).toBeEnabled();
      act(() => {
        if (change === "tenant") scope.tenant = "org-1";
        else useAuthStore.setState({ user: USER });
      });
      rerender(<ClaudeSubscriptionConnection />);
      expect(
        await screen.findByRole("button", { name: "Connect Claude subscription" }),
      ).toBeEnabled();
      await act(async () => finish?.(CONNECTED));
      expect(screen.queryByText("Connected · personal")).toBeNull();
      expect(client.getQueryData(qk.personalSubscriptions.claude("org-1:person-1"))).toEqual(
        AVAILABLE,
      );
      await userEvent.click(screen.getByRole("button", { name: "Connect Claude subscription" }));
      expect(await screen.findByLabelText("Claude sign-in code")).toHaveValue("");
    },
  );
});
