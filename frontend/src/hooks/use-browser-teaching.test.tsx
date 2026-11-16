import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import {
  TEACHING_IDS as ids,
  teachingFixture,
  teachingReviewFixture,
} from "@/test-utils/browser-teaching";
import type { BrowserTeaching } from "@/types/browser-teaching";
import { useBrowserTeaching, useTeachingStart } from "./use-browser-teaching";
import { teachingDeadlineLive } from "@/lib/browser-teaching-review";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
let client: QueryClient;
let current: BrowserTeaching;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  useAuthStore.setState({ user: { id: ids.owner } as never, accessToken: "test" });
  useOrgStore.setState({ activeOrgId: ids.org });
  current = teachingFixture();
  vi.mocked(apiClient.get).mockImplementation(async () => current as never);
});
afterEach(() => {
  cleanup();
  client.clear();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("owner teaching session", () => {
  it("does not publish a command result if the audience changes at mutation settlement", async () => {
    client = new QueryClient({
      mutationCache: new MutationCache({
        onSuccess: () => useOrgStore.setState({ activeOrgId: ids.other }),
      }),
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    vi.mocked(apiClient.get).mockImplementation(async (_path, options) => {
      if ((options?.headers as Record<string, string>)["X-Organization-Id"] !== ids.org)
        throw new ApiError(404, "Unavailable");
      return current as never;
    });
    vi.mocked(apiClient.post).mockResolvedValue(teachingFixture({ revision: 3 }) as never);
    const { result } = renderHook(() => useBrowserTeaching(ids.session), { wrapper });
    await waitFor(() => expect(result.current.session).toBeDefined());
    await act(async () => {
      await result.current.command.mutateAsync({ action: "stop", session: current });
    });
    expect(
      (
        client.getQueryData(qk.browserTeaching.detail(ids.owner, ids.org, ids.session)) as
          BrowserTeaching | undefined
      )?.revision,
    ).not.toBe(3);
    expect(result.current.session).toBeUndefined();
  });

  it("keeps capture deadlines current after the finite GET polling window ends", async () => {
    vi.useFakeTimers();
    current = teachingFixture({
      status: "paused",
      capture_ends_at: new Date(Date.now() + 240_000).toISOString(),
    });
    const { result } = renderHook(() => useBrowserTeaching(ids.session), { wrapper });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(181_000);
    });
    expect(result.current.pollingEnded).toBe(true);
    expect(teachingDeadlineLive(current.capture_ends_at, result.current.now)).toBe(true);
    const reads = vi.mocked(apiClient.get).mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(teachingDeadlineLive(current.capture_ends_at, result.current.now)).toBe(false);
    expect(apiClient.get).toHaveBeenCalledTimes(reads);
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("loads the exact private receipt and refuses invalid identities without fetching", async () => {
    const { result, rerender } = renderHook(({ id }) => useBrowserTeaching(id), {
      wrapper,
      initialProps: { id: "bad" },
    });
    expect(result.current.ready).toBe(false);
    expect(apiClient.get).not.toHaveBeenCalled();
    await act(async () => {
      expect(await result.current.refresh()).toBeUndefined();
    });
    rerender({ id: ids.session });
    await waitFor(() => expect(result.current.session?.id).toBe(ids.session));
    expect(apiClient.get).toHaveBeenCalledWith(
      `/browser-teachings/${ids.session}`,
      expect.objectContaining({ cache: "no-store", headers: { "X-Organization-Id": ids.org } }),
    );
  });
  it("withholds a mismatched response rather than displaying another capture", async () => {
    current = teachingFixture({ id: ids.other });
    const { result } = renderHook(() => useBrowserTeaching(ids.session), { wrapper });
    await waitFor(() => expect(result.current.query.isError).toBe(true));
    expect(result.current.session).toBeUndefined();
  });
  it.each([401, 403, 404])(
    "hides a previously read receipt when the fresh read refuses %s",
    async (status) => {
      const { result } = renderHook(() => useBrowserTeaching(ids.session), { wrapper });
      await waitFor(() => expect(result.current.session).toBeDefined());
      vi.mocked(apiClient.get).mockRejectedValue(new ApiError(status, "PRIVATE REFUSAL"));
      await act(async () => {
        await result.current.refresh();
      });
      expect(result.current.session).toBeUndefined();
    },
  );
  it("refetches a newer event revision without interpreting it as draft approval", async () => {
    const { result, rerender } = renderHook(({ rev }) => useBrowserTeaching(ids.session, rev), {
      wrapper,
      initialProps: { rev: 2 },
    });
    await waitFor(() => expect(result.current.session?.revision).toBe(2));
    current = teachingFixture({ revision: 3, status: "paused" });
    rerender({ rev: 3 });
    await waitFor(() => expect(result.current.session?.revision).toBe(3));
    expect(apiClient.post).not.toHaveBeenCalled();
  });
  it.each(["change", "stop", "discard", "propose"] as const)(
    "uses the explicit %s transition and reads its outcome",
    async (action) => {
      const next = teachingFixture({ revision: 3 });
      const method =
        action === "change"
          ? apiClient.patch
          : action === "discard"
            ? apiClient.delete
            : apiClient.post;
      vi.mocked(method).mockImplementation(async () => {
        current = next;
        return next as never;
      });
      const { result } = renderHook(() => useBrowserTeaching(ids.session), { wrapper });
      await waitFor(() => expect(result.current.session).toBeDefined());
      await act(async () => {
        await result.current.command.mutateAsync(
          action === "change"
            ? {
                action,
                session: current,
                body: { action: "review", review: teachingReviewFixture() },
              }
            : action === "propose"
              ? { action, session: current, revision: 2, body: { mode: "reviewed" } }
              : { action, session: current },
        );
      });
      expect(method).toHaveBeenCalledTimes(1);
      await waitFor(() => expect(result.current.session?.revision).toBe(3));
    },
  );
  it.each(["id", "run_id", "call_id", "tab_id", "agent_id", "target_skill_id"] as const)(
    "rejects a mutation response for a different %s",
    async (field) => {
      vi.mocked(apiClient.post).mockResolvedValue(teachingFixture({ [field]: ids.other }) as never);
      const { result } = renderHook(() => useBrowserTeaching(ids.session), { wrapper });
      await waitFor(() => expect(result.current.session).toBeDefined());
      await act(async () => {
        await expect(
          result.current.command.mutateAsync({ action: "stop", session: current }),
        ).rejects.toThrow("identity mismatch");
      });
      expect(result.current.session?.id).toBe(ids.session);
    },
  );
  it("keeps a more recent GET revision when an older mutation response arrives", async () => {
    let finish!: (value: never) => void;
    vi.mocked(apiClient.post).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const { result } = renderHook(() => useBrowserTeaching(ids.session), { wrapper });
    await waitFor(() => expect(result.current.session).toBeDefined());
    let pending!: Promise<BrowserTeaching>;
    act(() => {
      pending = result.current.command.mutateAsync({ action: "stop", session: current });
    });
    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    current = teachingFixture({ revision: 5 });
    client.setQueryData(qk.browserTeaching.detail(ids.owner, ids.org, ids.session), current);
    await act(async () => {
      finish(teachingFixture({ revision: 3 }) as never);
      await pending;
    });
    expect(result.current.session?.revision).toBe(5);
  });
  it("does not deliver delayed data after actor A -> B -> A", async () => {
    let finish!: (value: never) => void;
    vi.mocked(apiClient.get).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const { result } = renderHook(() => useBrowserTeaching(ids.session), { wrapper });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    act(() => {
      useAuthStore.setState({ user: { id: ids.other } as never });
      useAuthStore.setState({ user: { id: ids.owner } as never });
    });
    await act(async () => finish(current as never));
    await waitFor(() => expect(result.current.query.isError).toBe(true));
    expect(result.current.session).toBeUndefined();
  });
  it("bounds pending reads and restarts only GET checks", async () => {
    vi.useFakeTimers();
    current = teachingFixture({ generation_state: "queued" });
    const { result } = renderHook(() => useBrowserTeaching(ids.session), { wrapper });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(181_000);
    });
    expect(result.current.pollingEnded).toBe(true);
    const calls = vi.mocked(apiClient.get).mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(apiClient.get).toHaveBeenCalledTimes(calls);
    await act(async () => {
      await result.current.refresh();
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(result.current.pollingEnded).toBe(false);
    expect(apiClient.post).not.toHaveBeenCalled();
  });
});

describe("explicit teaching start", () => {
  const attempt = {
    kind: "start" as const,
    targetSkillId: null,
    body: {
      request_id: ids.session,
      run_id: ids.run,
      call_id: "teaching-call",
      tab_id: "main",
      takeover_id: ids.takeover,
      title: "Synthetic capture",
      allowed_origins: ["https://reports.example"],
    },
  };
  it("does not cache a Start after its successful response crosses an organization change", async () => {
    client = new QueryClient({
      mutationCache: new MutationCache({
        onSuccess: () => useOrgStore.setState({ activeOrgId: ids.other }),
      }),
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    vi.mocked(apiClient.post).mockResolvedValue(current as never);
    const { result } = renderHook(useTeachingStart, { wrapper });
    await act(async () => {
      await result.current.mutateAsync(attempt);
    });
    expect(
      client.getQueryData(qk.browserTeaching.detail(ids.owner, ids.org, ids.session)),
    ).toBeUndefined();
    expect(
      client.getQueryData(qk.browserTeaching.detail(ids.owner, ids.other, ids.session)),
    ).toBeUndefined();
  });
  it("stores only a matching acknowledged result in the owner cache", async () => {
    vi.mocked(apiClient.post).mockResolvedValue(current as never);
    const { result } = renderHook(useTeachingStart, { wrapper });
    await act(async () => {
      await result.current.mutateAsync(attempt);
    });
    expect(client.getQueryData(qk.browserTeaching.detail(ids.owner, ids.org, ids.session))).toEqual(
      current,
    );
  });
  it.each(["id", "run_id", "call_id", "tab_id", "target_skill_id"] as const)(
    "keeps a Start response with changed %s unresolved",
    async (field) => {
      vi.mocked(apiClient.post).mockResolvedValue(teachingFixture({ [field]: ids.other }) as never);
      const { result } = renderHook(useTeachingStart, { wrapper });
      await act(async () => {
        await expect(result.current.mutateAsync(attempt)).rejects.toThrow("identity mismatch");
      });
      expect(
        client.getQueryData(qk.browserTeaching.detail(ids.owner, ids.org, ids.session)),
      ).toBeUndefined();
    },
  );
});
