import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { useRoutineTools } from "./use-routine-tools";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { RoutineToolOptions } from "@/lib/routine-tools-api";
import { toast } from "sonner";
vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), put: vi.fn() } }));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));
const options: RoutineToolOptions = {
  items: [],
  unavailable_settings: [],
  unavailable_sources: [],
};
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    client,
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  };
}
beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ sessionOwnerId: "owner", user: null });
  useOrgStore.setState({ activeOrgId: "org" });
  vi.mocked(apiClient.get).mockResolvedValue(options);
  vi.mocked(apiClient.put).mockResolvedValue(options);
});
it("fetches exact scoped tool options and refreshes readiness after saving", async () => {
  const { client, wrapper } = setup();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const { result } = renderHook(() => useRoutineTools("agent", "routine"), { wrapper });
  await waitFor(() => expect(result.current.data).toEqual(options));
  expect(apiClient.get).toHaveBeenCalledWith("/agents/agent/triggers/routine/tools");
  await act(() => result.current.refetch());
  await act(() =>
    result.current.replace.mutateAsync([
      { capability_id: "sandbox", tool_id: "read_file", setting: "ask" },
    ]),
  );
  expect(apiClient.put).toHaveBeenCalledWith("/agents/agent/triggers/routine/tools", {
    settings: [{ capability_id: "sandbox", tool_id: "read_file", setting: "ask" }],
  });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.triggers.all() });
});
it("waits for the owner and an enabled source review", async () => {
  useAuthStore.setState({ sessionOwnerId: null });
  const { wrapper } = setup();
  const { result, rerender } = renderHook(
    ({ enabled }) => useRoutineTools("agent", "routine", { enabled }),
    { wrapper, initialProps: { enabled: false } },
  );
  expect(apiClient.get).not.toHaveBeenCalled();
  act(() => useAuthStore.setState({ sessionOwnerId: "owner" }));
  expect(apiClient.get).not.toHaveBeenCalled();
  rerender({ enabled: true });
  await waitFor(() => expect(result.current.data).toEqual(options));
});
it("isolates cached options when organization or session owner changes", async () => {
  const { wrapper } = setup();
  const { result } = renderHook(() => useRoutineTools("agent", "routine"), { wrapper });
  await waitFor(() => expect(result.current.data).toEqual(options));
  act(() => {
    useOrgStore.setState({ activeOrgId: "other-org" });
    useAuthStore.setState({ sessionOwnerId: "other-owner" });
  });
  expect(result.current.data).toBeUndefined();
  await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
});
it("reports a refused save and rereads the available tools", async () => {
  const error = new Error("Role changed");
  vi.mocked(apiClient.put).mockRejectedValue(error);
  const { wrapper } = setup();
  const { result } = renderHook(() => useRoutineTools("agent", "routine"), { wrapper });
  await waitFor(() => expect(result.current.data).toEqual(options));
  await act(async () => {
    await expect(result.current.replace.mutateAsync([])).rejects.toBe(error);
  });
  expect(toast.error).toHaveBeenCalledWith("Role changed");
  await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
});
it("does not cache a late save response in another session", async () => {
  let resolve: (data: RoutineToolOptions) => void = () => {
    throw new Error("No pending save");
  };
  vi.mocked(apiClient.put).mockImplementation(
    () =>
      new Promise<RoutineToolOptions>((done) => {
        resolve = done;
      }),
  );
  const { client, wrapper } = setup();
  const { result } = renderHook(() => useRoutineTools("agent", "routine"), { wrapper });
  await waitFor(() => expect(result.current.data).toEqual(options));
  let saving: Promise<unknown>;
  act(() => {
    saving = result.current.replace.mutateAsync([]);
  });
  await waitFor(() => expect(apiClient.put).toHaveBeenCalled());
  act(() => useOrgStore.setState({ activeOrgId: "other-org" }));
  const late = {
    items: [],
    unavailable_settings: [],
    unavailable_sources: ["private-old-account"],
  };
  await act(async () => {
    resolve(late);
    await saving;
  });
  expect(client.getQueryData(qk.triggers.toolSettings("owner", "org", "agent", "routine"))).toEqual(
    options,
  );
  expect(result.current.data).not.toEqual(late);
});

it.each(["owner", "organization", "signed-out"] as const)(
  "refuses an earlier dialog's save after %s changes",
  async (kind) => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useRoutineTools("agent", "routine"), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual(options));
    const save = result.current.replace.mutateAsync;
    await act(async () => {
      if (kind === "organization") useOrgStore.setState({ activeOrgId: "other" });
      else useAuthStore.setState({ sessionOwnerId: kind === "signed-out" ? null : "other" });
      await expect(save([])).rejects.toThrow("Session expired");
    });
    expect(apiClient.put).not.toHaveBeenCalled();
  },
);
it("refuses a mutation without an owner and supports the current authenticated user before persistence", async () => {
  useAuthStore.setState({ sessionOwnerId: null });
  const { wrapper } = setup();
  const { result } = renderHook(() => useRoutineTools("agent", "routine"), { wrapper });
  await act(async () => {
    await expect(result.current.replace.mutateAsync([])).rejects.toThrow("Session expired");
  });
  act(() =>
    useAuthStore.setState({
      user: {
        id: "live-user",
        email: "reader@example.com",
        is_active: true,
        created_at: "2026-11-26T00:00:00Z",
      },
    }),
  );
  await waitFor(() => expect(result.current.data).toEqual(options));
  await act(() => result.current.replace.mutateAsync([]));
  expect(apiClient.put).toHaveBeenCalled();
});
it("discards a response that arrives after sign-out", async () => {
  let resolve: (data: RoutineToolOptions) => void = () => {
    throw new Error("No pending mutation");
  };
  vi.mocked(apiClient.put).mockImplementation(
    () =>
      new Promise<RoutineToolOptions>((done) => {
        resolve = done;
      }),
  );
  const { client, wrapper } = setup();
  const { result } = renderHook(() => useRoutineTools("agent", "routine"), { wrapper });
  await waitFor(() => expect(result.current.data).toEqual(options));
  let pending: Promise<unknown>;
  act(() => {
    pending = result.current.replace.mutateAsync([]);
  });
  await waitFor(() => expect(apiClient.put).toHaveBeenCalled());
  act(() => useAuthStore.setState({ sessionOwnerId: null }));
  client.clear();
  await act(async () => {
    resolve(options);
    await pending;
  });
  expect(
    client.getQueryData(qk.triggers.toolSettings("owner", "org", "agent", "routine")),
  ).toBeUndefined();
});
