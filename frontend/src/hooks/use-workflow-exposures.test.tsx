import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import * as api from "@/lib/workflows/exposures-api";
import type { WorkflowExposureCreated } from "@/lib/workflows/types";

import { useWorkflowExposures } from "./use-workflow-exposures";

vi.mock("@/lib/workflows/exposures-api", () => ({
  listWorkflowExposures: vi.fn(),
  createWorkflowExposure: vi.fn(),
  updateWorkflowExposure: vi.fn(),
  deleteWorkflowExposure: vi.fn(),
  rotateWorkflowExposureSecret: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const created = { id: "e1", reveal_secret: "s" } as WorkflowExposureCreated;

beforeEach(() => vi.clearAllMocks());

describe("useWorkflowExposures", () => {
  it("lists exposures and runs every write against the workflow", async () => {
    vi.mocked(api.listWorkflowExposures).mockResolvedValue({ items: [created] });
    vi.mocked(api.createWorkflowExposure).mockResolvedValue(created);
    vi.mocked(api.updateWorkflowExposure).mockResolvedValue(created);
    vi.mocked(api.deleteWorkflowExposure).mockResolvedValue();
    vi.mocked(api.rotateWorkflowExposureSecret).mockResolvedValue(created);
    const { result } = renderHook(() => useWorkflowExposures("wf"), { wrapper });
    await waitFor(() => expect(result.current.exposures).toHaveLength(1));

    await act(() => result.current.create.mutateAsync({ adapter: "webhook" }));
    expect(toast.success).toHaveBeenCalledWith("Trigger added");
    await act(() => result.current.update.mutateAsync({ id: "e1", body: { is_active: false } }));
    expect(api.updateWorkflowExposure).toHaveBeenCalledWith("wf", "e1", { is_active: false });
    await act(() => result.current.rotate.mutateAsync("e1"));
    await act(() => result.current.remove.mutateAsync("e1"));
    expect(toast.success).toHaveBeenCalledWith("Trigger removed");
  });

  it("says why a write failed", async () => {
    vi.mocked(api.listWorkflowExposures).mockResolvedValue({ items: [] });
    vi.mocked(api.createWorkflowExposure).mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useWorkflowExposures("wf"), { wrapper });
    await act(async () => {
      await result.current.create.mutateAsync({ adapter: "schedule" }).catch(() => undefined);
    });
    expect(toast.error).toHaveBeenCalled();
    expect(result.current.exposures).toEqual([]);
  });
});
