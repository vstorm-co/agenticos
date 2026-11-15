import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { useAuthStore, useOrgStore } from "@/stores";
import type { ClaudeSubscriptionStatus } from "@/types/personal-subscriptions";
import { useClaudeSubscription } from "./use-claude-subscription";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));
const disconnected: ClaudeSubscriptionStatus = {
  available: true,
  connected: false,
  state: "disconnected",
  login_id: null,
  authorization_url: null,
  expires_at: null,
  error_code: null,
};
const connected: ClaudeSubscriptionStatus = {
  ...disconnected,
  connected: true,
  state: "connected",
};
const user = (id: string) => ({
  id,
  email: `${id}@example.test`,
  is_active: true,
  created_at: "2026-11-14T10:00:00Z",
});
const clients: QueryClient[] = [];
function setup(organizations = [{ id: "org-a" }, { id: "org-b" }]) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } },
  });
  clients.push(client);
  client.setQueryData(qk.organizations.list(), organizations);
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return { client, wrapper: Wrapper };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}
beforeEach(() => {
  vi.resetAllMocks();
  useAuthStore.setState({ user: user("person-a") });
  useOrgStore.setState({ activeOrgId: "org-a" });
  vi.mocked(apiClient.get).mockResolvedValue(disconnected);
  vi.mocked(apiClient.post).mockResolvedValue(connected);
});
afterEach(() => {
  for (const client of clients.splice(0)) client.clear();
});

describe("private Claude subscription actions", () => {
  it.each(["disabled", "account", "organization"] as const)(
    "refuses programmatic actions while %s readiness is missing",
    async (missing) => {
      if (missing === "account") useAuthStore.setState({ user: null });
      if (missing === "organization") useOrgStore.setState({ activeOrgId: null });
      const { wrapper } = setup(missing === "organization" ? [] : undefined);
      const { result } = renderHook(
        () => useClaudeSubscription({ enabled: missing !== "disabled" }),
        { wrapper },
      );
      expect(result.current.ready).toBe(false);

      await act(async () => {
        await result.current.start();
        await result.current.submit("login-1", "dummy-code");
        await result.current.cancel("login-1");
        await result.current.disconnect();
      });

      expect(apiClient.get).not.toHaveBeenCalled();
      expect(apiClient.post).not.toHaveBeenCalled();
      expect(result.current.action).toBeNull();
      expect(result.current.failed).toBe(false);
    },
  );

  it.each(["account", "organization"] as const)(
    "does not send an action when %s changes while the prior read is being cancelled",
    async (boundary) => {
      const { wrapper } = setup();
      const { result } = renderHook(() => useClaudeSubscription({ enabled: true }), { wrapper });
      await waitFor(() => expect(result.current.status.isSuccess).toBe(true));
      let starting!: Promise<void>;

      act(() => {
        starting = result.current.start();
        if (boundary === "account") useAuthStore.setState({ user: user("person-b") });
        else useOrgStore.setState({ activeOrgId: "org-b" });
      });
      await act(async () => starting);

      expect(apiClient.post).not.toHaveBeenCalled();
      expect(result.current.action).toBeNull();
      expect(result.current.failed).toBe(false);
    },
  );

  it.each(["account", "organization"] as const)(
    "refuses an old action callback after the %s changes",
    async (boundary) => {
      const { wrapper } = setup();
      const { result } = renderHook(() => useClaudeSubscription({ enabled: true }), { wrapper });
      await waitFor(() => expect(result.current.status.isSuccess).toBe(true));
      const oldStart = result.current.start;
      act(() => {
        if (boundary === "account") useAuthStore.setState({ user: user("person-b") });
        else useOrgStore.setState({ activeOrgId: "org-b" });
      });
      await act(async () => oldStart());
      expect(apiClient.post).not.toHaveBeenCalled();
      expect(result.current.action).toBeNull();
    },
  );

  it.each(["start", "submit", "cancel", "disconnect"] as const)(
    "stores only the accepted status after %s",
    async (action) => {
      const next: ClaudeSubscriptionStatus =
        action === "start"
          ? { ...disconnected, state: "awaiting_code", login_id: "login-1" }
          : action === "submit"
            ? connected
            : disconnected;
      vi.mocked(apiClient.post).mockResolvedValueOnce(next);
      const { client, wrapper } = setup();
      const { result } = renderHook(() => useClaudeSubscription({ enabled: true }), { wrapper });
      await waitFor(() => expect(result.current.status.isSuccess).toBe(true));

      await act(async () => {
        if (action === "start") await result.current.start();
        if (action === "submit") await result.current.submit("login-1", "dummy-code");
        if (action === "cancel") await result.current.cancel("login-1");
        if (action === "disconnect") await result.current.disconnect();
      });

      const path =
        action === "start"
          ? "/login"
          : action === "submit"
            ? "/login/code"
            : action === "cancel"
              ? "/login/cancel"
              : "/disconnect";
      const body =
        action === "submit"
          ? { login_id: "login-1", code: "dummy-code" }
          : action === "cancel"
            ? { login_id: "login-1" }
            : {};
      expect(apiClient.post).toHaveBeenCalledExactlyOnceWith(
        "/personal-subscriptions/claude" + path,
        body,
        { signal: expect.any(AbortSignal) },
      );
      expect(result.current.status.data).toEqual(next);
      expect(result.current.action).toBeNull();
      expect(result.current.failed).toBe(false);
      expect(client.getMutationCache().getAll()).toEqual([]);
      expect(
        JSON.stringify(
          client
            .getQueryCache()
            .getAll()
            .map((query) => query.state.data),
        ),
      ).not.toContain("dummy-code");
    },
  );

  it("keeps a failed action retryable without replacing the last accepted status", async () => {
    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("Connection unavailable"));
    const { wrapper } = setup();
    const { result } = renderHook(() => useClaudeSubscription({ enabled: true }), { wrapper });
    await waitFor(() => expect(result.current.status.isSuccess).toBe(true));

    await act(async () => result.current.start());
    expect(result.current.failed).toBe(true);
    expect(result.current.action).toBeNull();
    expect(result.current.status.data).toEqual(disconnected);

    await act(async () => result.current.start());
    expect(result.current.failed).toBe(false);
    expect(result.current.status.data).toEqual(connected);
    expect(apiClient.post).toHaveBeenCalledTimes(2);
  });

  it.each(
    (["resolve", "reject"] as const).flatMap((outcome) =>
      (["account", "organization", "unmount"] as const).map((boundary) => ({ outcome, boundary })),
    ),
  )(
    "does not publish a delayed $outcome after $boundary changes",
    async ({ outcome, boundary }) => {
      const pending = deferred<ClaudeSubscriptionStatus>();
      vi.mocked(apiClient.post).mockReturnValueOnce(pending.promise);
      const { client, wrapper } = setup();
      const { result, unmount } = renderHook(() => useClaudeSubscription({ enabled: true }), {
        wrapper,
      });
      await waitFor(() => expect(result.current.status.isSuccess).toBe(true));
      const previousScope = result.current.scope;
      let starting!: Promise<void>;
      act(() => {
        starting = result.current.start();
      });
      await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
      const signal = vi.mocked(apiClient.post).mock.calls[0]?.[2]?.signal;

      act(() => {
        if (boundary === "account") useAuthStore.setState({ user: user("person-b") });
        if (boundary === "organization") useOrgStore.setState({ activeOrgId: "org-b" });
        if (boundary === "unmount") unmount();
      });
      expect(signal?.aborted).toBe(true);
      await act(async () => {
        if (outcome === "resolve") pending.resolve(connected);
        else pending.reject(new Error("Old scope was refused"));
        await starting;
      });

      expect(
        client.getQueryData<ClaudeSubscriptionStatus>(
          qk.personalSubscriptions.claude(previousScope),
        )?.connected,
      ).not.toBe(true);
      if (boundary !== "unmount") {
        await waitFor(() => expect(result.current.status.data).toEqual(disconnected));
        expect(result.current.action).toBeNull();
        expect(result.current.failed).toBe(false);
      }
    },
  );
});
