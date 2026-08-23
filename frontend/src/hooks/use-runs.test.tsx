import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  useApprovals,
  useDelegatedRuns,
  usePrefetchRuns,
  useRunManifest,
  useResumeRun,
  useRun,
  useRuns,
  useRunTranscript,
  useSpend,
} from "./use-runs";
import { ApiError, apiClient } from "@/lib/api-client";

// `ApiError` stays real: the auto-resume path decides what to swallow by
// reading the refusal's class, status and details.
vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn() } };
});
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

  it("narrows by status set, surface, model and cost order on the wire", async () => {
    // The model is matched as the run recorded it - the label the dashboard's
    // card counts, which is what makes the hand-off from that bar one set.
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    const { result } = renderHook(
      () =>
        useRuns(undefined, {
          orderBy: "cost",
          statuses: ["failed", "budget_exceeded"],
          surface: "slack",
          modelLabel: "gpt-4o-mini",
        }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/runs", {
      params: {
        order_by: "cost",
        status: "failed,budget_exceeded",
        surface: "slack",
        model_label: "gpt-4o-mini",
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

  it("reads the newest page when asked for the tail of a long log", async () => {
    // The endpoint orders oldest-first and answers a hundred, so a trigger's
    // run-log after fifty fires showed only its oldest history and the reply just
    // fired could never appear on the page being polled.
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ run_id: "r", conversation_id: "c", items: [], total: 250 })
      .mockResolvedValueOnce({ run_id: "r", conversation_id: "c", items: [], total: 250 });
    const { result } = renderHook(() => useRunTranscript("run-9", "conversation", { tail: true }), {
      wrapper,
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenLastCalledWith("/runs/run-9/transcript", {
      params: { scope: "conversation", skip: "150" },
    });
  });

  it("asks for one page directly, with no discovery request before it", async () => {
    // The caller learned the total from a previous answer, which is where its
    // page number came from - so a second round trip to learn it again is a
    // request for something already known.
    vi.mocked(apiClient.get).mockResolvedValue({
      run_id: "r",
      conversation_id: "c",
      items: [],
      total: 250,
    });
    const { result } = renderHook(() => useRunTranscript("run-9", "conversation", { page: 1 }), {
      wrapper,
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledTimes(1);
    expect(apiClient.get).toHaveBeenCalledWith("/runs/run-9/transcript", {
      params: { scope: "conversation", skip: "100" },
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

  it("says a rejection as a rejection, in the catalog's words", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValue({ status: "rejected" });
    const { result } = renderHook(() => useApprovals(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.decide.mutateAsync({ id: "ap1", approved: false });

    expect(toast.success).toHaveBeenCalledWith("Rejected");
  });

  it("resumes the run once its last outstanding call is decided", async () => {
    // A decision is a click; continuing the run is a separate call the backend
    // keeps apart on purpose. The queue used to make only the first, which left
    // a run approved, undisputed, and parked forever (found on a live run).
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValue({ status: "approved", run_id: "run-9" });
    const { result } = renderHook(() => useApprovals(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.decide.mutateAsync({ id: "ap1", approved: true });

    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith("/runs/run-9/resume"));
  });

  it("does not resume while another call on the same run is still parked", async () => {
    // Resuming with a decision outstanding is a refusal the backend would make;
    // more importantly the run is not ready - the second call still needs its
    // answer, and the queue is where it gets one.
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "ap2", run_id: "run-9", status: "pending" }],
      total: 1,
    });
    vi.mocked(apiClient.post).mockResolvedValue({ status: "approved", run_id: "run-9" });
    const { result } = renderHook(() => useApprovals(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.decide.mutateAsync({ id: "ap1", approved: true });

    expect(apiClient.post).toHaveBeenCalledTimes(1);
    expect(apiClient.post).not.toHaveBeenCalledWith("/runs/run-9/resume");
  });

  it("swallows only the still-parked refusal when the cached page misled it", async () => {
    // The "anything still pending?" check reads one cached page of fifty, so a
    // run whose other parked call sits past those fifty reads as clear and the
    // resume is attempted. The backend's refusal is that check's answer
    // arriving late - toasted, it lands on the innocent person who just
    // decided correctly.
    const { toast } = await import("sonner");
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 51 });
    vi.mocked(apiClient.post).mockImplementation((path: string) =>
      path === "/runs/run-9/resume"
        ? Promise.reject(
            new ApiError(400, "1 tool call(s) on this run are still awaiting a decision", {
              error: {
                code: "BAD_REQUEST",
                message: "1 tool call(s) on this run are still awaiting a decision",
                details: { run_id: "run-9", pending: ["ap-51"] },
              },
            }),
          )
        : Promise.resolve({ status: "approved", run_id: "run-9" }),
    );
    const { result } = renderHook(() => useApprovals(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.decide.mutateAsync({ id: "ap1", approved: true });

    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith("/runs/run-9/resume"));
    await waitFor(() => expect(toast.error).not.toHaveBeenCalled());
  });

  it("still toasts an auto-resume that failed for any other reason", async () => {
    // Only the still-parked refusal is the check's own answer; a spec that can
    // no longer be built leaves the run parked with nothing outstanding, and
    // silence there is a run stuck forever with nobody told.
    const { toast } = await import("sonner");
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockImplementation((path: string) =>
      path === "/runs/run-9/resume"
        ? Promise.reject(
            new ApiError(400, "The version this run parked on can no longer be built", {
              error: {
                code: "BAD_REQUEST",
                message: "The version this run parked on can no longer be built",
                details: { run_id: "run-9" },
              },
            }),
          )
        : Promise.resolve({ status: "approved", run_id: "run-9" }),
    );
    const { result } = renderHook(() => useApprovals(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.decide.mutateAsync({ id: "ap1", approved: true });

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "The version this run parked on can no longer be built",
      ),
    );
  });

  it("still toasts an auto-resume the network dropped", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockImplementation((path: string) =>
      path === "/runs/run-9/resume"
        ? Promise.reject(new Error("Failed to fetch"))
        : Promise.resolve({ status: "approved", run_id: "run-9" }),
    );
    const { result } = renderHook(() => useApprovals(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.decide.mutateAsync({ id: "ap1", approved: true });

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Failed to fetch"));
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

describe("useResumeRun", () => {
  beforeEach(() => vi.clearAllMocks());

  it("continues the parked run and says so", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.post).mockResolvedValue({ run_id: "run-9", status: "running" });
    const { result } = renderHook(() => useResumeRun(), { wrapper });

    await result.current.mutateAsync("run-9");

    expect(apiClient.post).toHaveBeenCalledWith("/runs/run-9/resume");
    expect(toast.success).toHaveBeenCalledWith(
      "Run resumed - the agent picked up where it parked.",
    );
  });

  it("says a resume was refused rather than leaving the run looking picked up", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.post).mockRejectedValue(new Error("Approvals are still pending"));
    const { result } = renderHook(() => useResumeRun(), { wrapper });

    await expect(result.current.mutateAsync("run-9")).rejects.toThrow(
      "Approvals are still pending",
    );

    expect(toast.error).toHaveBeenCalledWith("Approvals are still pending");
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

  it("asks for nothing when the caller opted out", () => {
    // The Activity page disables this for a caller without runs:view - the
    // route refuses them, and the 403 would render as nothing spent.
    renderHook(() => useSpend(7, { enabled: false }), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
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

describe("usePrefetchRuns", () => {
  beforeEach(() => vi.clearAllMocks());

  it("warms both queries the detail view makes, for each neighbour named", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({});

    renderHook(() => usePrefetchRuns(["run-1", null, "run-3", undefined]), { wrapper });

    // The row and its transcript, per neighbour - the two requests a step would
    // otherwise make while somebody watches a skeleton.
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(4));
    expect(apiClient.get).toHaveBeenCalledWith("/runs/run-1");
    expect(apiClient.get).toHaveBeenCalledWith("/runs/run-1/transcript", {
      params: { scope: "conversation" },
    });
    expect(apiClient.get).toHaveBeenCalledWith("/runs/run-3");
  });

  it("asks for nothing at the edge of a thread", () => {
    renderHook(() => usePrefetchRuns([null, null]), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });
});

describe("useRunManifest", () => {
  beforeEach(() => vi.clearAllMocks());

  it("reads what the run handed its model", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ run_id: "run-1", tools: [] });

    const { result } = renderHook(() => useRunManifest("run-1"), { wrapper });

    await waitFor(() => expect(result.current.manifest).toBeDefined());
    expect(apiClient.get).toHaveBeenCalledWith("/runs/run-1/manifest");
  });

  it("surfaces the 404 rather than retrying it three times", async () => {
    // A run that recorded nothing is an answer, not a hiccup: retried, the panel
    // that says so arrives three round trips late.
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(404, "nothing recorded"));

    const { result } = renderHook(() => useRunManifest("run-1"), { wrapper });

    await waitFor(() => expect(result.current.error).toBeInstanceOf(ApiError));
    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });

  it("asks for nothing when the caller opts out", () => {
    renderHook(() => useRunManifest("run-1", { enabled: false }), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });
});
