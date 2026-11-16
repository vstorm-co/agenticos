import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { TEACHING_IDS as ids, teachingSummaryFixture } from "@/test-utils/browser-teaching";
import {
  useTeachingList,
  useTeachingPolicy,
  useTeachingPreference,
  useTeachingRun,
  useTeachingSkills,
} from "./use-browser-teaching-settings";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), put: vi.fn() } }));
let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => {
  vi.resetAllMocks();
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  useAuthStore.setState({ user: { id: ids.owner } as never, accessToken: "test" });
  useOrgStore.setState({ activeOrgId: ids.org });
});
afterEach(() => {
  cleanup();
  client.clear();
  vi.restoreAllMocks();
});

describe("teaching policy and member preference", () => {
  it("keeps policy reads disabled until requested, then writes a fetched generation", async () => {
    let policy = { enabled: false, generation: null as string | null, deployment_enabled: true };
    vi.mocked(apiClient.get).mockImplementation(async () => policy as never);
    vi.mocked(apiClient.put).mockImplementation(async () => {
      policy = { ...policy, enabled: true, generation: ids.other };
      return policy as never;
    });
    const { result, rerender } = renderHook(({ enabled }) => useTeachingPolicy(enabled), {
      wrapper,
      initialProps: { enabled: false },
    });
    expect(apiClient.get).not.toHaveBeenCalled();
    rerender({ enabled: true });
    await waitFor(() => expect(result.current.data?.enabled).toBe(false));
    await act(async () => {
      await result.current.update.mutateAsync({
        enabled: true,
        generation: result.current.data!.generation,
      });
    });
    expect(apiClient.put).toHaveBeenCalledWith(
      "/browser-teaching-policy",
      { enabled: true, generation: null },
      expect.objectContaining({ retryAfterRefresh: false }),
    );
    await waitFor(() => expect(result.current.data?.generation).toBe(ids.other));
  });
  it("reads current policy after a generation conflict and hides a refused fresh read", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      enabled: false,
      generation: null,
      deployment_enabled: true,
    } as never);
    vi.mocked(apiClient.put).mockRejectedValue(new ApiError(409, "changed"));
    const { result } = renderHook(() => useTeachingPolicy(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(403, "private"));
    await act(async () => {
      await expect(
        result.current.update.mutateAsync({ enabled: true, generation: null }),
      ).rejects.toBeInstanceOf(ApiError);
    });
    await waitFor(() => expect(result.current.data).toBeUndefined());
  });
  it("can revoke an enabled member preference after current admission is lost", async () => {
    let preference = { agent_id: ids.agent, enabled: true, generation: ids.other, allowed: false };
    vi.mocked(apiClient.get).mockImplementation(async () => preference as never);
    vi.mocked(apiClient.put).mockImplementation(async () => {
      preference = { ...preference, enabled: false };
      return preference as never;
    });
    const { result } = renderHook(() => useTeachingPreference(ids.agent), { wrapper });
    await waitFor(() => expect(result.current.data?.allowed).toBe(false));
    await act(async () => {
      await result.current.update.mutateAsync({ enabled: false, generation: ids.other });
    });
    expect(apiClient.put).toHaveBeenCalledWith(
      `/agents/${ids.agent}/browser-teaching-preference`,
      { enabled: false, generation: ids.other },
      expect.objectContaining({ retryAfterRefresh: false }),
    );
    await waitFor(() => expect(result.current.data?.enabled).toBe(false));
  });
  it("does not borrow another agent's preference or read an invalid agent", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      agent_id: ids.other,
      enabled: true,
      generation: null,
      allowed: true,
    } as never);
    const { result, rerender } = renderHook(({ id }) => useTeachingPreference(id), {
      wrapper,
      initialProps: { id: null as string | null },
    });
    expect(apiClient.get).not.toHaveBeenCalled();
    rerender({ id: "not-an-id" });
    expect(apiClient.get).not.toHaveBeenCalled();
    rerender({ id: ids.agent });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toBeUndefined();
    vi.mocked(apiClient.put).mockResolvedValue({
      agent_id: ids.other,
      enabled: false,
      generation: null,
      allowed: false,
    } as never);
    await act(async () => {
      await result.current.update.mutateAsync({ enabled: false, generation: null });
    });
    expect(result.current.data).toBeUndefined();
  });
  it.each(["policy", "preference"] as const)(
    "discards the %s mutation callback after the audience changes",
    async (kind) => {
      client = new QueryClient({
        mutationCache: new MutationCache({
          onSuccess: () => useOrgStore.setState({ activeOrgId: ids.other }),
        }),
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
      });
      const data =
        kind === "policy"
          ? { enabled: true, generation: ids.other, deployment_enabled: true }
          : { agent_id: ids.agent, enabled: true, generation: ids.other, allowed: true };
      vi.mocked(apiClient.get).mockRejectedValue(new ApiError(403, "not loaded"));
      vi.mocked(apiClient.put).mockResolvedValue(data as never);
      const usePolicy = kind === "policy";
      const { result } = renderHook(
        () => {
          const policy = useTeachingPolicy(usePolicy);
          const preference = useTeachingPreference(usePolicy ? null : ids.agent);
          return usePolicy ? policy.update : preference.update;
        },
        { wrapper },
      );
      await act(async () => {
        await result.current.mutateAsync({ enabled: true, generation: null });
      });
      const key = usePolicy
        ? qk.browserTeaching.policy(ids.owner, ids.org)
        : qk.browserTeaching.preference(ids.owner, ids.org, ids.agent);
      expect(client.getQueryData(key)).toBeUndefined();
    },
  );
  it("does not fetch any private settings before actor and tenant are known", () => {
    useAuthStore.setState({ user: null });
    useOrgStore.setState({ activeOrgId: null });
    renderHook(
      () => {
        useTeachingPolicy();
        useTeachingPreference(ids.agent);
        useTeachingList();
        useTeachingRun(ids.run, true);
        useTeachingSkills(true);
      },
      { wrapper },
    );
    expect(apiClient.get).not.toHaveBeenCalled();
  });
});

describe("private run and paginated choices", () => {
  it("withholds the run agent until the addressed run matches", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: ids.other, agent_id: ids.agent } as never);
    const { result, rerender } = renderHook(({ enabled }) => useTeachingRun(ids.run, enabled), {
      wrapper,
      initialProps: { enabled: false },
    });
    expect(apiClient.get).not.toHaveBeenCalled();
    rerender({ enabled: true });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toBeUndefined();
    vi.mocked(apiClient.get).mockResolvedValue({ id: ids.run, agent_id: ids.agent } as never);
    await act(async () => {
      await result.current.refetch();
    });
    await waitFor(() => expect(result.current.data?.agent_id).toBe(ids.agent));
  });
  it("continues skill pagination and terminates on an empty page without treating it as every skill", async () => {
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ items: [{ id: ids.skill, can_edit: true }], total: 3 } as never)
      .mockResolvedValueOnce({ items: [{ id: ids.other, can_edit: false }], total: 3 } as never)
      .mockResolvedValueOnce({ items: [], total: 3 } as never);
    const { result } = renderHook(() => useTeachingSkills(true), { wrapper });
    await waitFor(() => expect(result.current.hasNextPage).toBe(true));
    await act(async () => {
      await result.current.fetchNextPage();
    });
    await waitFor(() => expect(result.current.data?.pages).toHaveLength(2));
    expect(apiClient.get).toHaveBeenLastCalledWith(
      "/skills",
      expect.objectContaining({ params: { skip: "1", limit: "50", sort: "name" } }),
    );
    await act(async () => {
      await result.current.fetchNextPage();
    });
    await waitFor(() => expect(result.current.hasNextPage).toBe(false));
  });
  it("drops old skill choices after an authority refusal", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      items: [{ id: ids.skill }],
      total: 1,
    } as never);
    const { result } = renderHook(() => useTeachingSkills(true), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(403, "PRIVATE"));
    await act(async () => {
      await result.current.refetch();
    });
    await waitFor(() => expect(result.current.data).toBeUndefined());
  });
  it("uses the opaque cursor and explicitly resets an invalid next-page request", async () => {
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({
        items: [teachingSummaryFixture()],
        next_cursor: "opaque-owner-cursor",
      } as never)
      .mockRejectedValueOnce(
        new ApiError(400, "bad cursor", {
          error: {
            code: "BAD_REQUEST",
            message: "bad cursor",
            details: { reason_code: "invalid_cursor" },
          },
        }),
      )
      .mockResolvedValue({ items: [], next_cursor: null } as never);
    const { result } = renderHook(useTeachingList, { wrapper });
    await waitFor(() => expect(result.current.hasNextPage).toBe(true));
    await act(async () => {
      await result.current.fetchNextPage();
    });
    expect(apiClient.get).toHaveBeenLastCalledWith(
      "/browser-teachings",
      expect.objectContaining({ params: { limit: "20", cursor: "opaque-owner-cursor" } }),
    );
    await waitFor(() => expect(result.current.data).toBeUndefined());
    await act(async () => {
      await result.current.restart();
    });
    await waitFor(() => expect(result.current.data?.pages[0]?.items).toEqual([]));
    expect(apiClient.get).toHaveBeenLastCalledWith(
      "/browser-teachings",
      expect.objectContaining({ params: { limit: "20" } }),
    );
  });
  it("starts a new first page when switching organizations", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (_path, options) =>
      options?.headers &&
      (options.headers as Record<string, string>)["X-Organization-Id"] === ids.org
        ? ({ items: [teachingSummaryFixture()], next_cursor: "old-tenant-cursor" } as never)
        : ({ items: [], next_cursor: null } as never),
    );
    const { result } = renderHook(useTeachingList, { wrapper });
    await waitFor(() => expect(result.current.data?.pages[0]?.items).toHaveLength(1));
    act(() => useOrgStore.setState({ activeOrgId: ids.other }));
    await waitFor(() => expect(result.current.data?.pages[0]?.items).toEqual([]));
    expect(apiClient.get).toHaveBeenLastCalledWith(
      "/browser-teachings",
      expect.objectContaining({
        headers: { "X-Organization-Id": ids.other },
        params: { limit: "20" },
      }),
    );
  });
});
