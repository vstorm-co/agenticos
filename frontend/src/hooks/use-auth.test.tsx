import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { useAdoptSession, useAuth, useReauthenticate } from "./use-auth";
import { apiClient, ApiError } from "@/lib/api-client";
import { ROUTES } from "@/lib/constants";
import { useAuthStore, useConversationStore, useOrgStore } from "@/stores";
import type { User } from "@/types";
import type { ReactNode } from "react";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

/**
 * A client per test, reachable from the test body.
 *
 * `useAuth` empties it as a session begins and as one ends, so the assertions
 * about that need to hold the same instance the hook was handed.
 */
let client: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function user(overrides: Partial<User> = {}): User {
  return {
    id: "u-1",
    email: "kacper@example.com",
    is_active: true,
    created_at: "2026-07-01T00:00:00Z",
    ...overrides,
  } as User;
}

/**
 * Every test starts from a signed-out session with the module's own state released.
 *
 * `useAuth` keeps three things at module scope - whether `/auth/me` has already
 * run, the in-flight promise, and the token-refresh interval - so that one page
 * load makes one request however many components mount the hook. `logout` is what
 * releases all three, which makes it the honest way to reset between tests:
 * re-importing the module would give the hook a different store and a different
 * `ApiError` class than the ones asserted on here.
 */
beforeEach(async () => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.mocked(apiClient.get).mockResolvedValue(user());
  vi.mocked(apiClient.post).mockResolvedValue({});
  const { result, unmount } = renderHook(() => useAuth(), { wrapper });
  await act(async () => {
    await result.current.logout();
  });
  unmount();
  useAuthStore.setState({
    user: null,
    isAuthenticated: false,
    isLoading: false,
    accessToken: null,
  });
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue(user());
  vi.mocked(apiClient.post).mockResolvedValue({});
});

afterEach(() => {
  vi.useRealTimers();
});

describe("checking the session on load", () => {
  it("reads /auth/me and adopts the user", async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));
    expect(apiClient.get).toHaveBeenCalledWith("/auth/me");
  });

  it("keeps the access token out of the user object", async () => {
    // The token arrives in the body because the cookie is httpOnly, and it is
    // what the websocket authenticates with - but it is not a field of the user.
    vi.mocked(apiClient.get).mockResolvedValue({ ...user(), access_token: "t-1" });

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(useAuthStore.getState().accessToken).toBe("t-1"));
    expect(result.current.user).not.toHaveProperty("access_token");
  });

  it("has no token when the session came back without one", async () => {
    renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(useAuthStore.getState().user).not.toBeNull());
    expect(useAuthStore.getState().accessToken).toBeNull();
  });

  it("asks once however many components mount the hook", async () => {
    // Six panels on one page used to mean six `/auth/me` requests.

    renderHook(() => useAuth(), { wrapper });
    renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(useAuthStore.getState().isAuthenticated).toBe(true));
    renderHook(() => useAuth(), { wrapper });

    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });

  it("clears a persisted session the server no longer honours", async () => {
    useAuthStore.setState({ user: user(), isAuthenticated: true, accessToken: "stale" });
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(401, "Token expired"));

    renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(useAuthStore.getState().isAuthenticated).toBe(false));
    expect(useAuthStore.getState().accessToken).toBeNull();
  });
});

describe("signing in", () => {
  it("starts the session on an empty cache", async () => {
    // The query cache holds whoever was here last: their conversations, their
    // agents, the device names and IP addresses on their profile. A session
    // that ended without a logout - an expired cookie, a failed refresh - would
    // otherwise leave all of it to be served to the account that signs in next.
    // A session that ended without a logout - an expired cookie, a closed
    // laptop - so the browser still holds the account that filled it.
    useAuthStore.getState().setSessionOwnerId("u-1");
    client.setQueryData(["sessions", "list", 0], { items: [{ ip_address: "10.0.0.1" }] });
    useConversationStore.getState().setCurrentConversationId("c-1");
    vi.mocked(apiClient.post).mockResolvedValue({
      user: user({ id: "u-2" }),
      access_token: "t-2",
      message: "ok",
    });
    const { result } = renderHook(() => useAuth(), { wrapper });

    await act(async () => {
      await result.current.login({ email: "b@example.com", password: "pw" });
    });

    expect(client.getQueryData(["sessions", "list", 0])).toBeUndefined();
    expect(useConversationStore.getState().currentConversationId).toBeNull();
  });

  it("empties a cache nobody is recorded as owning", async () => {
    // A refused token refresh calls the store's `logout` directly: no owner
    // recorded, and the whole cache still there. "Nobody owns this" is not the
    // same as "there is nothing here".
    client.setQueryData(["sessions", "list", 0], { items: [{ ip_address: "10.0.0.1" }] });
    expect(useAuthStore.getState().sessionOwnerId).toBeNull();
    vi.mocked(apiClient.post).mockResolvedValue({
      user: user({ id: "u-4" }),
      access_token: "t-4",
      message: "ok",
    });
    const { result } = renderHook(() => useAuth(), { wrapper });

    await act(async () => {
      await result.current.login({ email: "d@example.com", password: "pw" });
    });

    expect(client.getQueryData(["sessions", "list", 0])).toBeUndefined();
  });

  it("re-reads the account after a flow that hands back no user", async () => {
    // The magic link answers with tokens only, and the auth check runs once per
    // page load - so a tab that had already asked kept the previous account
    // while every request authenticated as the new one.
    useAuthStore.getState().setSessionOwnerId("u-1");
    client.setQueryData(["sessions", "list", 0], { items: [{ ip_address: "10.0.0.1" }] });
    vi.mocked(apiClient.get).mockResolvedValue(user({ id: "u-5" }));
    const { result } = renderHook(() => useReauthenticate(), { wrapper });

    await act(async () => {
      await result.current();
    });

    expect(useAuthStore.getState().user?.id).toBe("u-5");
    expect(client.getQueryData(["sessions", "list", 0])).toBeUndefined();
  });

  it("leaves a transient auth failure alone", async () => {
    // `/auth/me` answering 502 nulls the user, which is not somebody else
    // arriving. Treating it as one would cost the person still signed in their
    // selected organization and agent on a bad network.
    useAuthStore.getState().setSessionOwnerId("u-1");
    client.setQueryData(["sessions", "list", 0], { items: [] });
    vi.mocked(apiClient.get).mockRejectedValue(new Error("502"));

    renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(useAuthStore.getState().isAuthenticated).toBe(false));
    expect(client.getQueryData(["sessions", "list", 0])).toEqual({ items: [] });
    expect(useAuthStore.getState().sessionOwnerId).toBe("u-1");
  });

  it("keeps the cache when the same account comes back", async () => {
    // The other half of keying on identity: a page reload adopts the persisted
    // user again, and treating that as a change of account would empty the
    // selected organization and agent on every refresh.
    vi.mocked(apiClient.post).mockResolvedValue({
      user: user(),
      access_token: "t-1",
      message: "ok",
    });
    const { result } = renderHook(() => useAuth(), { wrapper });
    await act(async () => {
      await result.current.login({ email: "kacper@example.com", password: "pw" });
    });
    client.setQueryData(["sessions", "list", 0], { items: [] });

    await act(async () => {
      await result.current.login({ email: "kacper@example.com", password: "pw" });
    });

    expect(client.getQueryData(["sessions", "list", 0])).toEqual({ items: [] });
  });

  it("empties the previous account on a sign-in that never calls login", async () => {
    // OAuth exchanges its code and adopts the session itself. Signing in
    // through Google is still signing in, and used to skip the cleanup.
    useAuthStore.getState().setSessionOwnerId("u-1");
    client.setQueryData(["sessions", "list", 0], { items: [{ ip_address: "10.0.0.1" }] });
    const { result } = renderHook(() => useAdoptSession(), { wrapper });

    act(() => result.current(user({ id: "u-3" }), "t-3"));

    expect(client.getQueryData(["sessions", "list", 0])).toBeUndefined();
    expect(useAuthStore.getState().user?.id).toBe("u-3");
  });

  it("adopts the user and the token the login answered with", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      user: user(),
      access_token: "t-1",
      message: "ok",
    });
    const { result } = renderHook(() => useAuth(), { wrapper });

    await act(async () => {
      await result.current.login({ email: "kacper@example.com", password: "secret" });
    });

    expect(apiClient.post).toHaveBeenCalledWith("/auth/login", {
      email: "kacper@example.com",
      password: "secret",
    });
    expect(useAuthStore.getState().accessToken).toBe("t-1");
  });

  it("sends an app admin to the dashboard and everybody else to the chat", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      user: user({ is_app_admin: true } as Partial<User>),
      access_token: "t-1",
      message: "ok",
    });
    const { result } = renderHook(() => useAuth(), { wrapper });

    await act(async () => {
      await result.current.login({ email: "a@example.com", password: "x" });
    });
    expect(push).toHaveBeenLastCalledWith(ROUTES.DASHBOARD);

    vi.mocked(apiClient.post).mockResolvedValue({ user: user(), access_token: "t", message: "ok" });
    await act(async () => {
      await result.current.login({ email: "b@example.com", password: "x" });
    });
    expect(push).toHaveBeenLastCalledWith(ROUTES.CHAT);
  });

  it("does not ask who is signed in after a login that just said so", async () => {
    // The login response carries the user and the token; a follow-up `/auth/me`
    // would be a second round trip for what is already in hand.
    vi.mocked(apiClient.post).mockResolvedValue({ user: user(), access_token: "t", message: "ok" });
    const { result } = renderHook(() => useAuth(), { wrapper });
    await act(async () => {
      await result.current.login({ email: "a@example.com", password: "x" });
    });
    vi.mocked(apiClient.get).mockClear();

    renderHook(() => useAuth(), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("stops loading and lets a refused login through to the form", async () => {
    // The form puts "Incorrect email or password" beside the fields; swallowing it
    // would leave a spinner and no explanation.
    vi.mocked(apiClient.post).mockRejectedValue(new ApiError(401, "Incorrect email or password"));
    const { result } = renderHook(() => useAuth(), { wrapper });

    await expect(
      result.current.login({ email: "a@example.com", password: "wrong" }),
    ).rejects.toThrow("Incorrect email or password");
    await waitFor(() => expect(useAuthStore.getState().isLoading).toBe(false));
  });

  it("registers without signing anybody in", async () => {
    // Registration may need a verification step, so it does not touch the session.
    vi.mocked(apiClient.post).mockResolvedValue({ id: "u-2", email: "new@example.com" });
    const { result } = renderHook(() => useAuth(), { wrapper });

    const registered = await result.current.register({
      email: "new@example.com",
      password: "secret123",
    });

    expect(apiClient.post).toHaveBeenCalledWith("/auth/register", {
      email: "new@example.com",
      password: "secret123",
    });
    expect(registered).toEqual({ id: "u-2", email: "new@example.com" });
    // Nobody was signed in as the new account: the session is still whoever
    // `/auth/me` answered with on mount.
    expect(useAuthStore.getState().user?.email).toBe("kacper@example.com");
  });
});

describe("signing out", () => {
  it("clears the session, says so, and goes to the login page", async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(useAuthStore.getState().isAuthenticated).toBe(true));

    await act(async () => {
      await result.current.logout();
    });

    expect(apiClient.post).toHaveBeenCalledWith("/auth/logout");
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(toast.success).toHaveBeenCalledWith("Logged out");
    expect(push).toHaveBeenCalledWith(ROUTES.LOGIN);
  });

  it("leaves nothing of the session behind", async () => {
    // The stores outlive a sign-out the way the cache does - they are module
    // scope, two of them `localStorage` - so the account signing in next was
    // shown the previous one's open conversation.
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(useAuthStore.getState().isAuthenticated).toBe(true));
    // Seeded after the mount adoption, which clears the stores itself - setting
    // it earlier would make this assertion pass without `logout` doing anything.
    client.setQueryData(["sessions", "list", 0], { items: [{ ip_address: "10.0.0.1" }] });
    useConversationStore.getState().setCurrentConversationId("c-1");
    useOrgStore.getState().setActiveOrgId("org-1");

    await act(async () => {
      await result.current.logout();
    });

    expect(client.getQueryData(["sessions", "list", 0])).toBeUndefined();
    expect(useConversationStore.getState().currentConversationId).toBeNull();
    expect(useOrgStore.getState().activeOrgId).toBeNull();
  });

  it("clears the session even when the server could not be told", async () => {
    // A logout that fails on the network still has to end the session locally;
    // leaving somebody signed in on a shared machine is the worse outcome.
    vi.mocked(apiClient.post).mockRejectedValue(new Error("offline"));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(useAuthStore.getState().isAuthenticated).toBe(true));

    await act(async () => {
      await result.current.logout();
    });

    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(push).toHaveBeenCalledWith(ROUTES.LOGIN);
  });

  it("checks the session again on the next mount", async () => {
    // The once-per-session guard has to be released, or signing in as somebody
    // else renders the previous user until a reload.
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(1));

    await act(async () => {
      await result.current.logout();
    });
    renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
  });
});

describe("refreshing the token by hand", () => {
  it("mints a token and re-reads who it belongs to", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ access_token: "fresh", message: "ok" });
    const { result } = renderHook(() => useAuth(), { wrapper });

    let refreshed: boolean | undefined;
    await act(async () => {
      refreshed = await result.current.refreshToken();
    });

    expect(refreshed).toBe(true);
    expect(apiClient.post).toHaveBeenCalledWith("/auth/refresh");
    expect(useAuthStore.getState().accessToken).toBe("fresh");
  });

  it("ends the session when the refresh itself is refused", async () => {
    // A 401 here means the refresh cookie is gone; staying on the page would
    // 401 every request behind it.
    vi.mocked(apiClient.post).mockRejectedValue(new ApiError(401, "No refresh cookie"));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(useAuthStore.getState().isAuthenticated).toBe(true));

    let refreshed: boolean | undefined;
    await act(async () => {
      refreshed = await result.current.refreshToken();
    });

    expect(refreshed).toBe(false);
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(push).toHaveBeenCalledWith(ROUTES.LOGIN);
  });

  it("keeps the session for a failure that is not a refusal", async () => {
    // A 502 from the proxy is not a reason to sign somebody out.
    vi.mocked(apiClient.post).mockRejectedValue(new ApiError(502, "Bad gateway"));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(useAuthStore.getState().isAuthenticated).toBe(true));

    let refreshed: boolean | undefined;
    await act(async () => {
      refreshed = await result.current.refreshToken();
    });

    expect(refreshed).toBe(false);
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
    expect(push).not.toHaveBeenCalledWith(ROUTES.LOGIN);
  });
});

describe("keeping the in-memory token fresh", () => {
  it("re-reads the token ahead of expiry, on one shared timer", async () => {
    // Access tokens last 15 minutes and the websocket authenticates with the
    // in-memory one; without this the chat goes "Offline" in a tab left open.
    vi.useFakeTimers();
    vi.mocked(apiClient.get).mockResolvedValue({ ...user(), access_token: "t-1" });
    renderHook(() => useAuth(), { wrapper });
    renderHook(() => useAuth(), { wrapper });
    await vi.waitFor(() => expect(useAuthStore.getState().isAuthenticated).toBe(true));

    vi.mocked(apiClient.get).mockResolvedValue({ ...user(), access_token: "t-2" });
    await act(async () => {
      vi.advanceTimersByTime(10 * 60 * 1000);
      await Promise.resolve();
    });

    await vi.waitFor(() => expect(useAuthStore.getState().accessToken).toBe("t-2"));
    // One interval, not one per mount: the session check on mount plus a single
    // refresh, from two mounted hooks.
    expect(vi.mocked(apiClient.get).mock.calls).toHaveLength(2);
  });

  it("does not ask on behalf of somebody who is not signed in", async () => {
    vi.useFakeTimers();
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(401, "no session"));
    renderHook(() => useAuth(), { wrapper });
    await vi.waitFor(() => expect(useAuthStore.getState().isAuthenticated).toBe(false));
    vi.mocked(apiClient.get).mockClear();

    await act(async () => {
      vi.advanceTimersByTime(10 * 60 * 1000);
      await Promise.resolve();
    });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("ignores a refresh that fails, because the next real request handles it", async () => {
    vi.useFakeTimers();
    vi.mocked(apiClient.get).mockResolvedValue({ ...user(), access_token: "t-1" });
    renderHook(() => useAuth(), { wrapper });
    await vi.waitFor(() => expect(useAuthStore.getState().accessToken).toBe("t-1"));

    vi.mocked(apiClient.get).mockRejectedValue(new Error("offline"));
    await act(async () => {
      vi.advanceTimersByTime(10 * 60 * 1000);
      await Promise.resolve();
    });

    expect(useAuthStore.getState().accessToken).toBe("t-1");
  });

  it("keeps the token it already has when a refresh answers without one", async () => {
    vi.useFakeTimers();
    vi.mocked(apiClient.get).mockResolvedValue({ ...user(), access_token: "t-1" });
    renderHook(() => useAuth(), { wrapper });
    await vi.waitFor(() => expect(useAuthStore.getState().accessToken).toBe("t-1"));

    vi.mocked(apiClient.get).mockResolvedValue(user());
    await act(async () => {
      vi.advanceTimersByTime(10 * 60 * 1000);
      await Promise.resolve();
    });

    expect(useAuthStore.getState().accessToken).toBe("t-1");
  });

  it("stops the timer on logout", async () => {
    vi.useFakeTimers();
    vi.mocked(apiClient.get).mockResolvedValue({ ...user(), access_token: "t-1" });
    const { result } = renderHook(() => useAuth(), { wrapper });
    await vi.waitFor(() => expect(useAuthStore.getState().isAuthenticated).toBe(true));

    await act(async () => {
      await result.current.logout();
    });
    vi.mocked(apiClient.get).mockClear();
    await act(async () => {
      vi.advanceTimersByTime(30 * 60 * 1000);
      await Promise.resolve();
    });

    expect(apiClient.get).not.toHaveBeenCalled();
  });
});
