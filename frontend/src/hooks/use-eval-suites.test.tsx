import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { evalSuite, suiteResult } from "@/test-utils/eval-suites";
import type { EvalSuiteInput } from "@/types/eval-suites";
import { useEvalSuiteResults, useEvalSuites, useVisibleEvalSuites } from "./use-eval-suites";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const INPUT: EvalSuiteInput = {
  name: "Nightly",
  description: null,
  dataset_id: "dataset-1",
  environment_id: null,
  threshold: {
    min_pass_rate: null,
    max_confirmed_regressions: 0,
    max_cost_per_pass_rise: null,
    max_p95_rise: null,
  },
  on_publish: true,
  on_promotion: false,
  on_dependency_change: false,
  schedule: null,
  max_run_usd: null,
};

async function suites() {
  const { result } = renderHook(() => useEvalSuites("agent-1"), { wrapper });
  await waitFor(() => expect(result.current.isLoading).toBe(false));
  return result;
}

describe("useEvalSuites", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({ items: [evalSuite()], total: 1 });
  });

  it("reads the agent's suites", async () => {
    const result = await suites();

    expect(apiClient.get).toHaveBeenCalledWith("/agents/agent-1/eval-suites");
    expect(result.current.suites).toHaveLength(1);
  });

  it("creates, saves, runs and removes a suite, saying so each time", async () => {
    const result = await suites();
    vi.mocked(apiClient.post).mockResolvedValue(evalSuite());
    vi.mocked(apiClient.patch).mockResolvedValue(evalSuite());
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);

    await act(() => result.current.create.mutateAsync(INPUT));
    await act(() => result.current.update.mutateAsync({ suiteId: "suite-1", input: INPUT }));
    await act(() => result.current.runNow.mutateAsync("suite-1"));
    await act(() => result.current.remove.mutateAsync("suite-1"));

    expect(apiClient.post).toHaveBeenCalledWith("/agents/agent-1/eval-suites", INPUT);
    expect(apiClient.patch).toHaveBeenCalledWith("/agents/agent-1/eval-suites/suite-1", INPUT);
    expect(apiClient.post).toHaveBeenCalledWith("/agents/agent-1/eval-suites/suite-1/run", {});
    expect(apiClient.delete).toHaveBeenCalledWith("/agents/agent-1/eval-suites/suite-1");
    expect(vi.mocked(toast.success).mock.calls.map(([text]) => text)).toEqual([
      "Suite created",
      "Suite saved",
      "Suite started",
      "Suite removed",
    ]);
  });

  it("pauses and resumes with is_active alone", async () => {
    const result = await suites();
    vi.mocked(apiClient.patch).mockResolvedValueOnce(evalSuite({ is_active: false }));
    vi.mocked(apiClient.patch).mockResolvedValueOnce(evalSuite({ is_active: true }));

    await act(() => result.current.setActive.mutateAsync({ suiteId: "suite-1", isActive: false }));
    await act(() => result.current.setActive.mutateAsync({ suiteId: "suite-1", isActive: true }));

    expect(apiClient.patch).toHaveBeenCalledWith("/agents/agent-1/eval-suites/suite-1", {
      is_active: false,
    });
    expect(vi.mocked(toast.success).mock.calls.map(([text]) => text)).toEqual([
      "Suite paused",
      "Suite resumed",
    ]);
  });

  it("says why a run, a pause or a removal was refused", async () => {
    const result = await suites();
    vi.mocked(apiClient.post).mockRejectedValue(new Error("paused"));
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("nope"));
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("nope"));

    await act(async () => {
      await result.current.runNow.mutateAsync("suite-1").catch(() => undefined);
      await result.current.setActive
        .mutateAsync({ suiteId: "suite-1", isActive: false })
        .catch(() => undefined);
      await result.current.remove.mutateAsync("suite-1").catch(() => undefined);
    });

    expect(toast.error).toHaveBeenCalledTimes(3);
  });

  it("prices a suite before it is saved", async () => {
    const result = await suites();
    vi.mocked(apiClient.post).mockResolvedValue({ fires_per_month: 30 });

    await act(() =>
      result.current.estimate.mutateAsync({
        dataset_id: "dataset-1",
        environment_id: null,
        schedule: null,
      }),
    );

    expect(apiClient.post).toHaveBeenCalledWith("/agents/agent-1/eval-suites/estimate", {
      dataset_id: "dataset-1",
      environment_id: null,
      schedule: null,
    });
  });
});

describe("useEvalSuiteResults", () => {
  beforeEach(() => vi.clearAllMocks());

  it("reads a page of one suite's results", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [suiteResult()], total: 21 });
    const { result } = renderHook(
      () => useEvalSuiteResults("agent-1", "suite-1", { skip: 20, limit: 20 }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(apiClient.get).toHaveBeenCalledWith(
      "/agents/agent-1/eval-suites/suite-1/results?skip=20&limit=20",
    );
    expect(result.current.total).toBe(21);
  });

  it("reads nothing until it is opened", () => {
    const { result } = renderHook(
      () => useEvalSuiteResults("agent-1", "suite-1", { enabled: false }),
      { wrapper },
    );

    expect(apiClient.get).not.toHaveBeenCalled();
    expect(result.current.results).toEqual([]);
  });
});

describe("useVisibleEvalSuites", () => {
  beforeEach(() => vi.clearAllMocks());

  it("reads every suite the reader may see", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [evalSuite()], total: 1 });
    const { result } = renderHook(() => useVisibleEvalSuites(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(apiClient.get).toHaveBeenCalledWith("/eval-suites");
    expect(result.current.suites).toHaveLength(1);
  });

  it("reads nothing while disabled", () => {
    const { result } = renderHook(() => useVisibleEvalSuites({ enabled: false }), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
    expect(result.current.suites).toEqual([]);
  });
});
