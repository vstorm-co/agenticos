import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import * as api from "@/lib/workflows/exposures-api";
import type { WorkflowExposureRead, WorkflowExposureWithSecret } from "@/lib/workflows/types";

import { useWorkflowExposure } from "./use-workflow-exposure";

vi.mock("@/lib/workflows/exposures-api", () => ({
  getWorkflowExposure: vi.fn(),
  updateWorkflowExposure: vi.fn(),
  rotateWorkflowExposureSecret: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const exposure = { id: "e1", is_active: true } as WorkflowExposureRead;

beforeEach(() => vi.clearAllMocks());

describe("useWorkflowExposure", () => {
  it("reads the exposure, pauses and resumes it, and rotates its secret", async () => {
    vi.mocked(api.getWorkflowExposure).mockResolvedValue(exposure);
    vi.mocked(api.updateWorkflowExposure)
      .mockResolvedValueOnce({ ...exposure, is_active: false })
      .mockResolvedValueOnce(exposure);
    vi.mocked(api.rotateWorkflowExposureSecret).mockResolvedValue({
      ...exposure,
      reveal_secret: "s",
    } as WorkflowExposureWithSecret);
    const { result } = renderHook(() => useWorkflowExposure("wf"), { wrapper });
    await waitFor(() => expect(result.current.exposure?.id).toBe("e1"));

    await act(() => result.current.setActive.mutateAsync({ id: "e1", active: false }));
    expect(api.updateWorkflowExposure).toHaveBeenCalledWith("wf", "e1", { is_active: false });
    expect(toast.success).toHaveBeenCalledWith("Trigger paused");
    await act(() => result.current.setActive.mutateAsync({ id: "e1", active: true }));
    expect(toast.success).toHaveBeenCalledWith("Trigger resumed");
    const rotated = await act(() => result.current.rotate.mutateAsync("e1"));
    expect(rotated.reveal_secret).toBe("s");
  });

  it("answers with none for a workflow that starts another way, and says why a write failed", async () => {
    vi.mocked(api.getWorkflowExposure).mockResolvedValue(null);
    vi.mocked(api.rotateWorkflowExposureSecret).mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useWorkflowExposure("wf"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.exposure).toBeNull();
    await act(async () => {
      await result.current.rotate.mutateAsync("e1").catch(() => undefined);
    });
    expect(toast.error).toHaveBeenCalled();
  });
});
