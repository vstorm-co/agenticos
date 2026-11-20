import {
  focusManager,
  onlineManager,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { useAppUpdate } from "./use-app-update";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));

const clients: QueryClient[] = [];

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  clients.push(client);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

async function advance(milliseconds = 10) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(milliseconds);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubEnv("NEXT_PUBLIC_APP_BUILD_ID", "loaded-build");
  vi.mocked(apiClient.get).mockReset().mockResolvedValue({ buildId: "loaded-build" });
  focusManager.setFocused(true);
  onlineManager.setOnline(true);
});

afterEach(() => {
  for (const client of clients.splice(0)) client.clear();
  focusManager.setFocused(undefined);
  onlineManager.setOnline(true);
  vi.unstubAllEnvs();
  vi.useRealTimers();
});

describe("deployed frontend updates", () => {
  it("deduplicates consumers and discovers a different build after a minute", async () => {
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ buildId: "loaded-build" })
      .mockResolvedValue({ buildId: "replacement-build" });
    const { wrapper } = setup();
    const hook = renderHook(() => [useAppUpdate(), useAppUpdate()], { wrapper });
    await advance();

    expect(hook.result.current).toEqual([false, false]);
    expect(apiClient.get).toHaveBeenCalledTimes(1);
    expect(apiClient.get).toHaveBeenCalledWith("/app-version", {
      cache: "no-store",
      signal: expect.any(AbortSignal),
    });
    await advance(60_000);
    expect(hook.result.current).toEqual([true, true]);
    expect(apiClient.get).toHaveBeenCalledTimes(2);
  });

  it("pauses hidden-tab polling and checks immediately when the app becomes visible", async () => {
    const { wrapper } = setup();
    const hook = renderHook(() => useAppUpdate(), { wrapper });
    await advance();
    focusManager.setFocused(false);
    await advance(120_000);
    expect(apiClient.get).toHaveBeenCalledTimes(1);

    vi.mocked(apiClient.get).mockResolvedValue({ buildId: "replacement-build" });
    await act(async () => {
      focusManager.setFocused(true);
    });
    await advance();
    expect(hook.result.current).toBe(true);
    expect(apiClient.get).toHaveBeenCalledTimes(2);
  });

  it("checks again on reconnect even while the previous answer is fresh", async () => {
    const { wrapper } = setup();
    const hook = renderHook(() => useAppUpdate(), { wrapper });
    await advance();
    onlineManager.setOnline(false);
    vi.mocked(apiClient.get).mockResolvedValue({ buildId: "replacement-build" });
    await act(async () => {
      onlineManager.setOnline(true);
    });
    await advance();
    expect(hook.result.current).toBe(true);
    expect(apiClient.get).toHaveBeenCalledTimes(2);
  });

  it("keeps an offered update through navigation and stops polling or refetching it", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ buildId: "replacement-build" });
    const { client, wrapper } = setup();
    const hook = renderHook(() => useAppUpdate(), { wrapper });
    await advance();
    expect(hook.result.current).toBe(true);
    hook.unmount();

    vi.mocked(apiClient.get).mockRejectedValue(new Error("temporarily unavailable"));
    await advance(120_000);
    const reopened = renderHook(() => useAppUpdate(), { wrapper });
    await act(async () => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
      onlineManager.setOnline(false);
      onlineManager.setOnline(true);
      await client.invalidateQueries();
    });
    await advance(120_000);
    expect(reopened.result.current).toBe(true);
    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });

  it("does not mistake a failed check for an update and retries at the next interval", async () => {
    vi.mocked(apiClient.get)
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue({ buildId: "replacement-build" });
    const { wrapper } = setup();
    const hook = renderHook(() => useAppUpdate(), { wrapper });
    await advance();
    expect(hook.result.current).toBe(false);
    expect(apiClient.get).toHaveBeenCalledTimes(1);
    await advance(60_000);
    expect(hook.result.current).toBe(true);
    expect(apiClient.get).toHaveBeenCalledTimes(2);
  });

  it.each([null, {}, { buildId: null }, { buildId: 42 }, { buildId: "" }])(
    "does not offer an update for missing or malformed metadata: %j",
    async (response) => {
      vi.mocked(apiClient.get).mockResolvedValue(response);
      const { wrapper } = setup();
      const hook = renderHook(() => useAppUpdate(), { wrapper });
      await advance();
      expect(hook.result.current).toBe(false);
    },
  );

  it("does not check a tab with no compiled build identity", async () => {
    vi.stubEnv("NEXT_PUBLIC_APP_BUILD_ID", undefined);
    const { wrapper } = setup();
    const hook = renderHook(() => useAppUpdate(), { wrapper });
    await advance(120_000);
    expect(hook.result.current).toBe(false);
    expect(apiClient.get).not.toHaveBeenCalled();
  });
});
