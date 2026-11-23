import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { KEY_DRAFT_POLL_MS, useCaseKeyDraft } from "./use-case-key-draft";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));
const toastError = vi.fn();
vi.mock("sonner", () => ({ toast: { error: (...args: unknown[]) => toastError(...args) } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const URL = "/datasets/d1/cases/c1/key-draft";
const draft = (status: "running" | "ready" | "failed") => ({
  id: "k1",
  case_id: "c1",
  status,
  keys: status === "ready" ? [{ key: "Invoice", value: "INV-7" }] : [],
  error: null,
  created_at: "2026-11-20T00:00:00Z",
  finished_at: null,
});

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useCaseKeyDraft", () => {
  it("asks nothing of a reader who may not edit the case", () => {
    const { result } = renderHook(() => useCaseKeyDraft("d1", "c1", { enabled: false }), {
      wrapper,
    });
    expect(apiClient.get).not.toHaveBeenCalled();
    expect(result.current).toMatchObject({ draft: null, loading: false, error: null });
  });

  it("reads a case with no draft as none, and another refusal as an error", async () => {
    vi.mocked(apiClient.get).mockRejectedValueOnce(new ApiError(404, "No drafted keys"));
    const { result } = renderHook(() => useCaseKeyDraft("d1", "c1", { enabled: true }), {
      wrapper,
    });
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith(URL);
    expect(result.current).toMatchObject({ draft: null, error: null });

    vi.mocked(apiClient.get).mockRejectedValueOnce(new ApiError(403, "No"));
    const other = renderHook(() => useCaseKeyDraft("d2", "c2", { enabled: true }), { wrapper });
    await waitFor(() => expect(other.result.current.error).toBeInstanceOf(ApiError));
    expect(other.result.current.draft).toBeNull();
  });

  it("asks again while the keys are listed, and stops once they are", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce(draft("running"))
      .mockResolvedValue(draft("ready"));
    const { result } = renderHook(() => useCaseKeyDraft("d1", "c1", { enabled: true }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.draft?.status).toBe("running"));

    await act(() => vi.advanceTimersByTimeAsync(KEY_DRAFT_POLL_MS));
    await waitFor(() => expect(result.current.draft?.status).toBe("ready"));
    const asked = vi.mocked(apiClient.get).mock.calls.length;
    await act(() => vi.advanceTimersByTimeAsync(KEY_DRAFT_POLL_MS * 2));
    expect(apiClient.get).toHaveBeenCalledTimes(asked);
    vi.useRealTimers();
  });

  it("starts a draft and dismisses it, saying when either is refused", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(null);
    vi.mocked(apiClient.post).mockResolvedValueOnce(draft("running"));
    vi.mocked(apiClient.delete).mockResolvedValueOnce(undefined);
    const { result } = renderHook(() => useCaseKeyDraft("d1", "c1", { enabled: true }), {
      wrapper,
    });

    act(() => result.current.start());
    await waitFor(() => expect(result.current.draft?.status).toBe("running"));
    expect(apiClient.post).toHaveBeenCalledWith(URL);

    act(() => result.current.dismiss());
    await waitFor(() => expect(result.current.draft).toBeNull());
    expect(apiClient.delete).toHaveBeenCalledWith(URL);

    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("offline"));
    vi.mocked(apiClient.delete).mockRejectedValueOnce(new Error("offline"));
    act(() => result.current.start());
    act(() => result.current.dismiss());
    await waitFor(() => expect(toastError).toHaveBeenCalledTimes(2));
  });
});
