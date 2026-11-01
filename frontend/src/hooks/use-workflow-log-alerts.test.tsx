import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/lib/workflows/log-alerts-api";
import type { LogAlertInput, LogAlertRule } from "@/lib/workflows/types";

import { useWorkflowLogAlerts } from "./use-workflow-log-alerts";

vi.mock("@/lib/workflows/log-alerts-api", () => ({
  listLogAlerts: vi.fn(),
  createLogAlert: vi.fn(),
  updateLogAlert: vi.fn(),
  deleteLogAlert: vi.fn(),
}));
const toasts = vi.hoisted(() => ({ done: vi.fn(), error: vi.fn() }));
vi.mock("@/lib/toast", () => ({ toastDone: toasts.done }));
vi.mock("sonner", () => ({ toast: { error: toasts.error } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const INPUT = { name: "x" } as LogAlertInput;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listLogAlerts).mockResolvedValue([{ id: "r1" } as LogAlertRule]);
});

describe("useWorkflowLogAlerts", () => {
  it("reads the rules, and none until they arrive", async () => {
    const { result } = renderHook(() => useWorkflowLogAlerts("wf"), { wrapper });
    expect(result.current.rules).toEqual([]);
    await waitFor(() => expect(result.current.rules).toHaveLength(1));
    expect(api.listLogAlerts).toHaveBeenCalledWith("wf");
  });

  it("hands a failed read on as an error, not as no rules", async () => {
    vi.mocked(api.listLogAlerts).mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useWorkflowLogAlerts("wf"), { wrapper });
    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.rules).toEqual([]);
  });

  it("saves and deletes, says so, and reads the rules again", async () => {
    vi.mocked(api.createLogAlert).mockResolvedValue({} as LogAlertRule);
    vi.mocked(api.updateLogAlert).mockResolvedValue({} as LogAlertRule);
    vi.mocked(api.deleteLogAlert).mockResolvedValue(undefined);
    const { result } = renderHook(() => useWorkflowLogAlerts("wf"), { wrapper });
    await waitFor(() => expect(result.current.rules).toHaveLength(1));

    await act(() => result.current.create.mutateAsync(INPUT));
    await act(() => result.current.update.mutateAsync({ ruleId: "r1", patch: { enabled: false } }));
    await act(() => result.current.remove.mutateAsync("r1"));

    expect(api.createLogAlert).toHaveBeenCalledWith("wf", INPUT);
    expect(api.updateLogAlert).toHaveBeenCalledWith("wf", "r1", { enabled: false });
    expect(api.deleteLogAlert).toHaveBeenCalledWith("wf", "r1");
    expect(toasts.done).toHaveBeenCalledTimes(3);
    await waitFor(() => expect(vi.mocked(api.listLogAlerts).mock.calls.length).toBeGreaterThan(1));
  });

  it("says why a delete failed, in the server's words", async () => {
    vi.mocked(api.deleteLogAlert).mockRejectedValue(new Error("Not allowed"));
    const { result } = renderHook(() => useWorkflowLogAlerts("wf"), { wrapper });
    await act(() => result.current.remove.mutateAsync("r1").catch(() => undefined));
    expect(toasts.error).toHaveBeenCalledWith("Not allowed");
    expect(toasts.done).not.toHaveBeenCalled();
  });

  it("hands out a toast for a failure the caller handles itself", async () => {
    const { result } = renderHook(() => useWorkflowLogAlerts("wf"), { wrapper });
    result.current.failed(new Error("Not allowed"));
    expect(toasts.error).toHaveBeenCalledWith("Not allowed");
  });
});
