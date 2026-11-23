import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { KEY_COVERAGE_POLL_MS, useKeyCoverage } from "./use-key-coverage";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));
const toastError = vi.fn();
vi.mock("sonner", () => ({ toast: { error: (...args: unknown[]) => toastError(...args) } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const URL = "/datasets/d1/key-coverage";
const report = (status: "running" | "ready" | "failed") => ({
  id: "r1",
  agent_id: "a1",
  dataset_id: "d1",
  dataset_version: 2,
  status,
  items: [],
  unseen_sources: 0,
  current: true,
  sources_changed: false,
  error: null,
  created_at: "2026-11-20T00:00:00Z",
  finished_at: null,
});

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useKeyCoverage", () => {
  it("reads a pair with no report as none, and another refusal as an error", async () => {
    vi.mocked(apiClient.get).mockRejectedValueOnce(new ApiError(404, "No report"));
    const { result } = renderHook(() => useKeyCoverage("d1", "a1"), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith(URL, { params: { agent_id: "a1" } });
    expect(result.current.report).toBeNull();

    vi.mocked(apiClient.get).mockRejectedValueOnce(new ApiError(403, "No"));
    const other = renderHook(() => useKeyCoverage("d2", "a2"), { wrapper });
    await waitFor(() => expect(other.result.current.loading).toBe(false));
    expect(other.result.current.report).toBeNull();
    expect(other.result.current.error).toBeInstanceOf(ApiError);
  });

  it("asks again while the keys are judged, and stops once they are", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce(report("running"))
      .mockResolvedValue(report("ready"));
    const { result } = renderHook(() => useKeyCoverage("d1", "a1"), { wrapper });
    await waitFor(() => expect(result.current.report?.status).toBe("running"));

    await act(() => vi.advanceTimersByTimeAsync(KEY_COVERAGE_POLL_MS));
    await waitFor(() => expect(result.current.report?.status).toBe("ready"));
    const asked = vi.mocked(apiClient.get).mock.calls.length;
    await act(() => vi.advanceTimersByTimeAsync(KEY_COVERAGE_POLL_MS * 2));
    expect(apiClient.get).toHaveBeenCalledTimes(asked);
    vi.useRealTimers();
  });

  it("starts a report, saying when that is refused", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(null);
    vi.mocked(apiClient.post).mockResolvedValueOnce(report("running"));
    const { result } = renderHook(() => useKeyCoverage("d1", "a1"), { wrapper });

    act(() => result.current.start());
    await waitFor(() => expect(result.current.report?.status).toBe("running"));
    expect(apiClient.post).toHaveBeenCalledWith(URL, { agent_id: "a1" });

    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("offline"));
    act(() => result.current.start());
    await waitFor(() => expect(toastError).toHaveBeenCalledTimes(1));
  });
});
