import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  useBackgroundJobActions,
  useBackgroundJobs,
  useBackgroundJobsOverview,
} from "./use-background-jobs";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { BackgroundJob } from "@/types/background-jobs";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));
const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

let client: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const JOB: BackgroundJob = {
  id: "j-1",
  kind: "ingest-document",
  pool: "ingest",
  status: "dead",
  priority: 0,
  attempts: 2,
  max_attempts: 2,
  organization_id: null,
  schedule_name: null,
  worker_id: null,
  last_error: "the child process was stopped by the memory watchdog",
  run_after: "2026-10-19T10:00:00Z",
  created_at: "2026-10-19T10:00:00Z",
  started_at: null,
  finished_at: "2026-10-19T10:01:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

describe("the overview", () => {
  it("is one request for the page's header", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      counts: {},
      kinds: [],
      workers: [],
      schedules: [],
    });
    const { result } = renderHook(() => useBackgroundJobsOverview(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiClient.get).toHaveBeenCalledWith("/admin/background-jobs");
  });
});

describe("the job list", () => {
  it("asks with the filters and follows the two-part cursor to the next page", async () => {
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({
        items: [JOB],
        next_before: "2026-10-19T10:00:00Z",
        next_before_id: "j-1",
      })
      .mockResolvedValueOnce({ items: [], next_before: null, next_before_id: null });
    const { result } = renderHook(() => useBackgroundJobs({ status: "dead", pool: "ingest" }), {
      wrapper,
    });

    await waitFor(() => expect(result.current.hasNextPage).toBe(true));
    expect(apiClient.get).toHaveBeenLastCalledWith("/admin/background-jobs/jobs", {
      params: { limit: "50", status: "dead", pool: "ingest" },
    });

    await act(() => result.current.fetchNextPage());
    await waitFor(() => expect(result.current.hasNextPage).toBe(false));
    expect(apiClient.get).toHaveBeenLastCalledWith("/admin/background-jobs/jobs", {
      params: {
        limit: "50",
        status: "dead",
        pool: "ingest",
        before: "2026-10-19T10:00:00Z",
        before_id: "j-1",
      },
    });
  });

  it("asks for everything when nothing is filtered", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [],
      next_before: null,
      next_before_id: null,
    });
    const { result } = renderHook(() => useBackgroundJobs({}), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiClient.get).toHaveBeenCalledWith("/admin/background-jobs/jobs", {
      params: { limit: "50" },
    });
  });
});

describe("the actions", () => {
  it("retry, cancel and resume each post, say so and refresh the whole page", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({});
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useBackgroundJobActions(), { wrapper });

    await act(() => result.current.retry.mutateAsync(JOB));
    await act(() => result.current.cancel.mutateAsync(JOB));
    await act(() =>
      result.current.resume.mutateAsync({ kind: "ingest-document", organization_id: null }),
    );
    await act(() =>
      result.current.resume.mutateAsync({ kind: "ingest-document", organization_id: "o-1" }),
    );

    expect(vi.mocked(apiClient.post).mock.calls.map((call) => call[0])).toEqual([
      "/admin/background-jobs/jobs/j-1/retry",
      "/admin/background-jobs/jobs/j-1/cancel",
      "/admin/background-jobs/kinds/ingest-document/resume",
      "/admin/background-jobs/kinds/ingest-document/resume",
    ]);
    // The whole kind names no organization; one organization's pause names it.
    expect(vi.mocked(apiClient.post).mock.calls[2]?.[2]).toBeUndefined();
    expect(vi.mocked(apiClient.post).mock.calls[3]?.[2]).toEqual({
      params: { organization_id: "o-1" },
    });
    expect(toastSuccess.mock.calls.map((call) => call[0])).toEqual([
      "The job is queued again.",
      "The job is cancelled.",
      "Jobs of this kind are claimed again.",
      "Jobs of this kind are claimed again.",
    ]);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.admin.backgroundJobs() });
  });

  it("a refused action is a toast with what the server said", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useBackgroundJobActions(), { wrapper });

    await act(async () => {
      await result.current.retry.mutateAsync(JOB).catch(() => undefined);
    });

    expect(toastError).toHaveBeenCalledTimes(1);
    expect(toastSuccess).not.toHaveBeenCalled();
  });
});
