import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import * as api from "@/lib/workflows/evals-api";
import type { EvalCaseList, EvalRun } from "@/lib/workflows/types";

import { useStepEvals } from "./use-step-evals";

vi.mock("@/lib/workflows/evals-api", () => ({
  listStepEvals: vi.fn(),
  createStepEval: vi.fn(),
  deleteStepEval: vi.fn(),
  tryStepEvals: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const run = (pending: number) => ({ id: "r1", pending, results: [] }) as unknown as EvalRun;

beforeEach(() => vi.clearAllMocks());

describe("useStepEvals", () => {
  it("reads the step's cases, writes, removes and tries them", async () => {
    vi.mocked(api.listStepEvals).mockResolvedValue({ items: [], latest: null } as EvalCaseList);
    vi.mocked(api.tryStepEvals).mockResolvedValue(run(0));
    const { result } = renderHook(() => useStepEvals("wf", "n1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.cases).toEqual([]);
    expect(result.current.latest).toBeNull();

    const input = {
      name: "Refund",
      run_input: {},
      outputs: {},
      expectation: { kind: "contains" as const, field: "text", value: "refund" },
    };
    await act(() => result.current.create.mutateAsync(input));
    await act(() => result.current.remove.mutateAsync("e1"));
    await act(() => result.current.run.mutateAsync());

    expect(api.createStepEval).toHaveBeenCalledWith("wf", "n1", input);
    expect(api.deleteStepEval).toHaveBeenCalledWith("wf", "e1");
    expect(api.tryStepEvals).toHaveBeenCalledWith("wf", "n1");
  });

  it("reads the list again while a try still has cases running", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(api.listStepEvals)
      .mockResolvedValueOnce({ items: [], latest: run(1) } as EvalCaseList)
      .mockResolvedValue({ items: [], latest: run(0) } as EvalCaseList);
    const { result } = renderHook(() => useStepEvals("wf", "n1"), { wrapper });
    await waitFor(() => expect(result.current.latest?.pending).toBe(1));

    await act(() => vi.advanceTimersByTimeAsync(2100));

    await waitFor(() => expect(result.current.latest?.pending).toBe(0));
    vi.useRealTimers();
  });

  it("says why a write failed", async () => {
    vi.mocked(api.listStepEvals).mockResolvedValue({ items: [], latest: null } as EvalCaseList);
    vi.mocked(api.tryStepEvals).mockRejectedValue(new Error("no"));
    const { result } = renderHook(() => useStepEvals("wf", "n1"), { wrapper });
    await act(async () => {
      await result.current.run.mutateAsync().catch(() => undefined);
    });
    expect(toast.error).toHaveBeenCalled();
  });
});
