import { focusManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { useReleaseUpdate } from "./use-release-update";
vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));
afterEach(() => {
  focusManager.setFocused(undefined);
  vi.useRealTimers();
  vi.clearAllMocks();
});
it("checks again automatically while the app stays open and deduplicates consumers", async () => {
  vi.useFakeTimers();
  vi.mocked(apiClient.get)
    .mockResolvedValueOnce({ latest: null })
    .mockResolvedValue({
      latest: {
        version: "1.29.0",
        url: "https://github.com/vstorm-co/agenticos/releases/tag/v1.29.0",
      },
    });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const hook = renderHook(() => [useReleaseUpdate(), useReleaseUpdate()], { wrapper });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10);
  });
  expect(apiClient.get).toHaveBeenCalledTimes(1);
  expect(hook.result.current[0]?.data).toEqual({ latest: null });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(30 * 60_000);
  });
  expect(apiClient.get).toHaveBeenCalledTimes(2);
  expect(hook.result.current[1]?.data?.latest?.version).toBe("1.29.0");
  hook.unmount();
  client.clear();
});

it("checks stale release metadata when the app regains focus despite the app-wide default", async () => {
  vi.useFakeTimers();
  vi.mocked(apiClient.get).mockResolvedValue({ latest: null });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const hook = renderHook(() => useReleaseUpdate(), { wrapper });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10);
  });
  focusManager.setFocused(false);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5 * 60_000);
  });
  expect(apiClient.get).toHaveBeenCalledTimes(1);
  await act(async () => {
    focusManager.setFocused(true);
    await vi.advanceTimersByTimeAsync(10);
  });
  expect(apiClient.get).toHaveBeenCalledTimes(2);
  hook.unmount();
  client.clear();
});
