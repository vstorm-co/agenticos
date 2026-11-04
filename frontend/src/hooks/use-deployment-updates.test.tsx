import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { useDeploymentUpdates } from "./use-deployment-updates";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));
afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});
const state = { configured: true, reachable: true, pipeline_url: null, operation: null };
const operation = {
  id: "a".repeat(32),
  version: "1.33.0",
  phase: "preparing",
  created_at: 1,
  updated_at: 1,
  scheduled_for: null,
  commit: "abc",
  previous_commit: "def",
  reason: null,
  backup_id: null,
  images: {},
};
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(() => useDeploymentUpdates(), { wrapper });
}
it("reads real status and refetches it after an explicit action", async () => {
  vi.mocked(apiClient.get).mockResolvedValue(state);
  vi.mocked(apiClient.post).mockResolvedValue({});
  const hook = mount();
  await waitFor(() => expect(hook.result.current.status.isSuccess).toBe(true));
  expect(apiClient.get).toHaveBeenCalledWith(
    "/admin/updates",
    expect.objectContaining({ signal: expect.any(AbortSignal) }),
  );
  await act(async () => {
    await hook.result.current.action.mutateAsync({
      kind: "prepare",
      payload: { version: "1.33.0" },
    });
  });
  expect(apiClient.post).toHaveBeenCalledWith("/admin/updates/prepare", { version: "1.33.0" });
  expect(apiClient.get).toHaveBeenCalledTimes(2);
});
it("rejects malformed status rather than treating it as unconfigured", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ configured: true });
  const hook = mount();
  await waitFor(() => expect(hook.result.current.status.isError).toBe(true));
});
it.each(["preparing", "succeeded"])(
  "polls %s operations at the appropriate interval",
  async (phase) => {
    vi.useFakeTimers();
    vi.mocked(apiClient.get).mockResolvedValue({ ...state, operation: { ...operation, phase } });
    const hook = mount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(apiClient.get).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(apiClient.get).toHaveBeenCalledTimes(phase === "preparing" ? 2 : 1);
    hook.unmount();
  },
);
