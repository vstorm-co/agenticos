import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  useApprovals,
  useDelegatedRuns,
  useRun,
  useRuns,
  useRunTranscript,
  useSpend,
} from "./use-runs";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useRuns", () => {
  beforeEach(() => vi.clearAllMocks());

  it("reads the whole organization by default", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    const { result } = renderHook(() => useRuns(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/runs", undefined);
  });

  it("narrows to one agent, and counts what it did as a delegate", async () => {
    // The per-agent question takes the opposite arithmetic to the bill: a
    // delegate's rows are the only record of its own spend, so an agent that
    // only ever runs as somebody's delegate would otherwise have no history at
    // all beside a spend figure that is not zero.
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    const { result } = renderHook(() => useRuns("a1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/runs", {
      params: { agent_id: "a1", include_delegations: "true" },
    });
  });

  it("leaves the feed's own order unsaid, so the default call stays bodyless", async () => {
    // `started_at` descending is the server's default. Sending it would only
    // change the cache key and the request shape for no behaviour, so the
    // unfiltered, unsorted call carries no params at all.
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    const { result } = renderHook(
      () => useRuns(undefined, { orderBy: "started_at", descending: true }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/runs", undefined);
  });

  it("sorts by duration and filters the slow runs in SQL, not over a page", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    const { result } = renderHook(
      () =>
        useRuns(undefined, {
          orderBy: "duration",
          descending: false,
          tookOverMs: 30_000,
          startedFrom: "2026-08-01T00:00:00.000Z",
          startedTo: "2026-08-31T23:59:59.999Z",
        }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/runs", {
      params: {
        order_by: "duration",
        descending: "false",
        took_over_ms: "30000",
        started_from: "2026-08-01T00:00:00.000Z",
        started_to: "2026-08-31T23:59:59.999Z",
      },
    });
  });

  it("narrows by status set, surface and cost order on the wire", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    const { result } = renderHook(
      () =>
        useRuns(undefined, {
          orderBy: "cost",
          statuses: ["failed", "budget_exceeded"],
          surface: "slack",
        }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/runs", {
      params: {
        order_by: "cost",
        status: "failed,budget_exceeded",
        surface: "slack",
      },
    });
  });

  it("fetches nothing for a caller that is not ready to ask", () => {
    // The Activity tab mounts before the organization is resolved; a request sent
    // then reads another organization's runs or none at all.
    renderHook(() => useRuns("a1", { enabled: false }), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("hands back the failure rather than an empty history", async () => {
    // An empty list and a refused read look identical on the page, and only one
    // of them is worth showing an error for.
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Missing required permission"));
    const { result } = renderHook(() => useRuns(), { wrapper });

    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current.runs).toEqual([]);
  });

  it("narrows to the runs somebody rated down when asked", async () => {
    // The highest-signal queue here: the answers real people said were wrong.
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    const { result } = renderHook(() => useRuns(undefined, { rated: "down" }), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/runs", { params: { rated: "down" } });
  });

  it("narrows by person and version, and pages by rows to skip", async () => {
    // The filter bar's two identity narrowings and the pager's offset, in the
    // route's own names - each computed in SQL over the whole history.
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    const { result } = renderHook(
      () => useRuns(undefined, { userId: "user-7", agentVersionId: "ver-2", skip: 50 }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/runs", {
      params: { user_id: "user-7", agent_version_id: "ver-2", skip: "50" },
    });
  });
});

describe("useRunTranscript", () => {
  beforeEach(() => vi.clearAllMocks());

  it("reads one run's transcript, where the ratings and their comments live", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      run_id: "run-9",
      conversation_id: "c1",
      items: [],
      total: 0,
    });
    const { result } = renderHook(() => useRunTranscript("run-9"), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/runs/run-9/transcript", undefined);
  });

  it("reads the whole thread when asked for the conversation scope", async () => {
    // The detail view shows the run in context, so it asks for the thread and
    // scrolls to the run - the run-only scope stays the wire's default.
    vi.mocked(apiClient.get).mockResolvedValue({
      run_id: "run-9",
      conversation_id: "c1",
      items: [],
      total: 0,
    });
    const { result } = renderHook(() => useRunTranscript("run-9", "conversation"), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/runs/run-9/transcript", {
      params: { scope: "conversation" },
    });
  });

  it("hands back the failure rather than an empty transcript", async () => {
    // A run with nothing rated down and a request that failed are the same
    // absence to the surface, and only one of them is worth an error.
    vi.mocked(apiClient.get).mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useRunTranscript("run-9"), { wrapper });

    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current.transcript).toBeUndefined();
  });
});

describe("useRun", () => {
  beforeEach(() => vi.clearAllMocks());

  it("reads one run by id, because a delegated one is not in the list", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "run-77" });
    const { result } = renderHook(() => useRun("run-77"), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/runs/run-77");
    expect(result.current.run).toEqual({ id: "run-77" });
  });

  it("hands back the refusal rather than an absent run", async () => {
    // "This run was deleted" and "the request was refused" are the same absence,
    // and only one of them is the reader's problem.
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Missing required permission"));
    const { result } = renderHook(() => useRun("run-77"), { wrapper });

    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current.run).toBeUndefined();
  });
});

describe("useDelegatedRuns", () => {
  beforeEach(() => vi.clearAllMocks());

  it("asks for one run's delegations by parent", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "run-child" }], total: 1 });
    const { result } = renderHook(() => useDelegatedRuns("run-parent"), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/runs", {
      params: { parent_run_id: "run-parent" },
    });
    expect(result.current.total).toBe(1);
  });
});

describe("useApprovals", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists what is waiting on a person", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "ap1", tool_id: "send_email", tool_args: { to: "a@b.c" } }],
      total: 1,
    });
    const { result } = renderHook(() => useApprovals(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.approvals).toHaveLength(1);
  });

  it("sends the decision and an optional note", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValue({ status: "rejected" });

    const { result } = renderHook(() => useApprovals(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.decide.mutateAsync({
      id: "ap1",
      approved: false,
      note: "wrong customer",
    });

    expect(apiClient.post).toHaveBeenCalledWith("/approvals/ap1", {
      approved: false,
      note: "wrong customer",
    });
  });

  it("says which way a decision went", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValue({ status: "approved" });
    const { result } = renderHook(() => useApprovals(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.decide.mutateAsync({ id: "ap1", approved: true });

    expect(toast.success).toHaveBeenCalledWith("Approved");
  });

  it("surfaces a refused second decision instead of leaving the queue silent", async () => {
    // The server refuses a decision on an approval somebody else already decided,
    // which is exactly what two people opening the queue at once produces.
    const { toast } = await import("sonner");
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockRejectedValue(new Error("Already decided"));
    const { result } = renderHook(() => useApprovals(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await expect(result.current.decide.mutateAsync({ id: "ap1", approved: true })).rejects.toThrow(
      "Already decided",
    );

    expect(toast.error).toHaveBeenCalledWith("Already decided");
  });
});

describe("useSpend", () => {
  beforeEach(() => vi.clearAllMocks());

  it("asks for the requested window", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      period_days: 7,
      month_to_date_usd: "1.23",
      by_agent: [],
    });
    const { result } = renderHook(() => useSpend(7), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/spend", { params: { days: "7" } });
    expect(result.current.spend?.month_to_date_usd).toBe("1.23");
  });
});

describe("dashboard freshness", () => {
  beforeEach(() => vi.clearAllMocks());

  /** The app's real defaults - without them this test proves nothing. */
  function appWrapper({ children }: { children: ReactNode }) {
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false, staleTime: 5 * 60 * 1000, refetchOnWindowFocus: false },
      },
    });
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }

  it("asks again when the tab regains focus", async () => {
    // The RUNS figure and Run history read this while an agent runs elsewhere,
    // so on the app-wide five-minute cache they would sit at "0 runs" beside a
    // Spend tab that already counted them until a full page reload.
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    const { result } = renderHook(() => useRuns(), { wrapper: appWrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledTimes(1);

    focusManager.setFocused(false);
    focusManager.setFocused(true);

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
  });
});
