import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { useBundleTransfer } from "./use-bundle-transfer";
import {
  applyBundleTransfer,
  getBundleTransfer,
  startBundleExport,
  startBundleUpload,
  uploadBundleFile,
  type TransferOperation,
} from "@/lib/portability-api";

vi.mock("@/lib/portability-api", () => ({
  applyBundleTransfer: vi.fn(),
  getBundleTransfer: vi.fn(),
  startBundleExport: vi.fn(),
  startBundleUpload: vi.fn(),
  uploadBundleFile: vi.fn(),
}));
const row = (status: TransferOperation["status"]): TransferOperation => ({
  id: "id",
  request_id: "request",
  direction: "import",
  phase: "prepare",
  status,
  revision: 1,
  completed_bytes: 0,
  total_bytes: 5,
  expires_at: "2026-11-26T12:00:00Z",
  error_code: null,
  preview: null,
  receipt: null,
  can_download: false,
});
function Wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
        })
      }
    >
      {children}
    </QueryClientProvider>
  );
}
beforeEach(() => vi.resetAllMocks());

it("polls an admitted export and never queues it a second time", async () => {
  vi.mocked(startBundleExport).mockResolvedValue(row("queued"));
  vi.mocked(getBundleTransfer).mockResolvedValue(row("ready"));
  vi.mocked(applyBundleTransfer).mockResolvedValue(row("ready"));
  const { result } = renderHook(() => useBundleTransfer(true), { wrapper: Wrapper });
  await act(() =>
    result.current.exportZip.mutateAsync({ rootId: "agent", requestId: "request", resources: {} }),
  );
  await waitFor(() => expect(result.current.transfer.data?.status).toBe("ready"), {
    timeout: 2500,
  });
  expect(startBundleExport).toHaveBeenCalledTimes(1);
  expect(getBundleTransfer).toHaveBeenCalledWith("id", expect.any(AbortSignal));
  await act(() => result.current.apply.mutateAsync({}));
});

it("retries interrupted upload against the original ticket and can reset for a new file", async () => {
  vi.mocked(startBundleUpload).mockResolvedValue(row("awaiting_upload"));
  vi.mocked(getBundleTransfer).mockResolvedValue(row("awaiting_upload"));
  vi.mocked(uploadBundleFile)
    .mockRejectedValueOnce(new Error("Connection lost"))
    .mockResolvedValueOnce(row("review"));
  vi.mocked(applyBundleTransfer).mockResolvedValue(row("ready"));
  const { result } = renderHook(() => useBundleTransfer(true), { wrapper: Wrapper });
  const request = { file: new File(["bytes"], "agent.zip"), requestId: "request" };
  await act(async () => {
    await expect(result.current.uploadZip.mutateAsync(request)).rejects.toThrow("Connection lost");
  });
  await waitFor(() => expect(result.current.error).toBeTruthy());
  await act(() => result.current.uploadZip.mutateAsync(request));
  expect(startBundleUpload).toHaveBeenCalledTimes(1);
  await act(() => result.current.apply.mutateAsync({}));
  vi.mocked(getBundleTransfer).mockResolvedValue(row("ready"));
  await act(() => result.current.uploadZip.mutateAsync(request));
  expect(uploadBundleFile).toHaveBeenCalledTimes(2);
  act(() => result.current.reset());
  expect(result.current.transfer.data).toBeUndefined();
});

it("refuses manual actions without a selected transfer", async () => {
  const { result } = renderHook(() => useBundleTransfer(true), { wrapper: Wrapper });
  await act(async () => {
    await expect(result.current.apply.mutateAsync({})).rejects.toThrow("No reviewed transfer");
  });
  await act(async () => {
    const response = await result.current.transfer.refetch();
    expect(response.error?.message).toBe("No transfer selected");
  });
});
