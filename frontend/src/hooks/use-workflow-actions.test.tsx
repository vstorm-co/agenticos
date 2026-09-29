import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { ApiError } from "@/lib/api-client";
import * as api from "@/lib/workflows/workflows-api";
import type { WorkflowDetail } from "@/lib/workflows/types";

import { useWorkflowActions } from "./use-workflow-actions";

vi.mock("@/lib/workflows/workflows-api", () => ({
  updateWorkflow: vi.fn(),
  setWorkflowActive: vi.fn(),
  archiveWorkflow: vi.fn(),
  unarchiveWorkflow: vi.fn(),
  deleteWorkflow: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const detail = (overrides: Partial<WorkflowDetail> = {}) =>
  ({ id: "wf", name: "Leads", trigger_active: true, ...overrides }) as WorkflowDetail;

beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

describe("useWorkflowActions", () => {
  it("writes each answer into the workflow's detail and says what happened", async () => {
    vi.mocked(api.updateWorkflow).mockResolvedValue(detail({ name: "Leads 2" }));
    vi.mocked(api.setWorkflowActive)
      .mockResolvedValueOnce(detail({ trigger_active: true }))
      .mockResolvedValueOnce(detail({ trigger_active: false }));
    vi.mocked(api.archiveWorkflow).mockResolvedValue(detail({ status: "archived" }));
    vi.mocked(api.unarchiveWorkflow).mockResolvedValue(detail({ status: "published" }));
    const { result } = renderHook(() => useWorkflowActions(), { wrapper });

    await act(() => result.current.update.mutateAsync({ id: "wf", update: { name: "Leads 2" } }));
    expect(client.getQueryData<WorkflowDetail>(["workflows", "wf"])?.name).toBe("Leads 2");
    await act(() => result.current.setActive.mutateAsync({ id: "wf", active: true }));
    await act(() => result.current.setActive.mutateAsync({ id: "wf", active: false }));
    await act(() => result.current.archive.mutateAsync("wf"));
    await act(() => result.current.unarchive.mutateAsync("wf"));

    expect(vi.mocked(toast.success).mock.calls.map(([text]) => text)).toEqual([
      "Workflow switched on.",
      "Workflow paused.",
      "Workflow archived. Its trigger is paused.",
      "Workflow restored.",
    ]);
  });

  it("forgets a deleted workflow, and says why when something is refused", async () => {
    client.setQueryData(["workflows", "wf"], detail());
    vi.mocked(api.deleteWorkflow).mockResolvedValue(undefined);
    vi.mocked(api.archiveWorkflow).mockRejectedValue(new ApiError(409, "Still in use"));
    const { result } = renderHook(() => useWorkflowActions(), { wrapper });

    await act(() => result.current.remove.mutateAsync("wf"));
    expect(client.getQueryData(["workflows", "wf"])).toBeUndefined();
    expect(toast.success).toHaveBeenCalledWith("Workflow deleted.");

    await act(() => result.current.archive.mutateAsync("wf").catch(() => undefined));
    expect(toast.error).toHaveBeenCalledWith("Still in use");
  });
});
