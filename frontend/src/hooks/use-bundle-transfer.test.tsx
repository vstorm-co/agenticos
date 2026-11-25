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

it("restores an owner-scoped operation without queuing work or exposing an unverified cached receipt", async () => {
  const { useAuthStore, useOrgStore } = await import("@/stores");
  const { qk } = await import("@/lib/query-keys");
  const { transferSessionKey, writeTransferSession } = await import("@/lib/transfer-session");
  const id = "aeac9081-9af3-4055-b738-1f4f7741af71";
  useAuthStore.setState({
    user: {
      id: "restore-user",
      email: "restore@example.com",
      is_active: true,
      created_at: "2026-01-01",
    },
  });
  useOrgStore.setState({ activeOrgId: "restore-org" });
  writeTransferSession(transferSessionKey("restore-org", "restore-user", "import:workflow"), id);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const cached = {
    ...row("ready"),
    id,
    receipt: { roots: { "workflow/root": "new-workflow" }, created: {}, reused: {}, skipped: [] },
  };
  client.setQueryData(qk.portability.transfer("restore-org", "restore-user", id), cached);
  const pending = Promise.withResolvers<TransferOperation>();
  vi.mocked(getBundleTransfer).mockReturnValue(pending.promise);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(() => useBundleTransfer(true, "import:workflow"), { wrapper });
  await waitFor(() => expect(getBundleTransfer).toHaveBeenCalledWith(id, expect.any(AbortSignal)));
  expect(result.current.transfer.data).toBeUndefined();
  pending.reject(new Error("Access revoked"));
  await waitFor(() => expect(result.current.restoreFailed).toBe(true));
  expect(result.current.transfer.data).toBeUndefined();
  await new Promise((resolve) => setTimeout(resolve, 1100));
  expect(getBundleTransfer).toHaveBeenCalledTimes(1);
  expect(startBundleExport).not.toHaveBeenCalled();
  expect(startBundleUpload).not.toHaveBeenCalled();
  act(() => result.current.reset());
  expect(result.current.restoreFailed).toBe(false);
  useAuthStore.setState({ user: null });
  useOrgStore.setState({ activeOrgId: null });
  sessionStorage.clear();
});

it("restores verified metadata and isolates a later organization switch", async () => {
  const { useAuthStore, useOrgStore } = await import("@/stores");
  const { transferSessionKey, writeTransferSession } = await import("@/lib/transfer-session");
  const id = "aeac9081-9af3-4055-b738-1f4f7741af71";
  useAuthStore.setState({
    user: {
      id: "restore-user",
      email: "restore@example.com",
      is_active: true,
      created_at: "2026-01-01",
    },
  });
  useOrgStore.setState({ activeOrgId: "restore-org" });
  writeTransferSession(transferSessionKey("restore-org", "restore-user", "import:workflow"), id);
  vi.mocked(getBundleTransfer).mockResolvedValue({ ...row("review"), id });
  const { result } = renderHook(() => useBundleTransfer(true, "import:workflow"), {
    wrapper: Wrapper,
  });
  await waitFor(() => expect(result.current.transfer.data?.id).toBe(id));
  act(() => useOrgStore.setState({ activeOrgId: "another-org" }));
  expect(result.current.transfer.data).toBeUndefined();
  expect(startBundleUpload).not.toHaveBeenCalled();
  useAuthStore.setState({ user: null });
  useOrgStore.setState({ activeOrgId: null });
  sessionStorage.clear();
});

it("renders server markup without reading tab-persisted operations", async () => {
  const { renderToString } = await import("react-dom/server");
  function Probe() {
    useBundleTransfer(false, "import:workflow");
    return null;
  }
  expect(() =>
    renderToString(
      <Wrapper>
        <Probe />
      </Wrapper>,
    ),
  ).not.toThrow();
  expect(startBundleExport).not.toHaveBeenCalled();
});

it("refreshes imported dependencies after the worker receipt, not when applying merely queues work", async () => {
  const { qk } = await import("@/lib/query-keys");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(qk.kb.list(), ["Original KB"]);
  let current = row("review");
  vi.mocked(startBundleUpload).mockResolvedValue(row("awaiting_upload"));
  vi.mocked(uploadBundleFile).mockResolvedValue(current);
  vi.mocked(getBundleTransfer).mockImplementation(async () => current);
  vi.mocked(applyBundleTransfer).mockImplementation(async () => {
    current = { ...row("queued"), phase: "apply" };
    return current;
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(() => useBundleTransfer(true), { wrapper });
  await act(() =>
    result.current.uploadZip.mutateAsync({
      file: new File(["data"], "bundle.zip"),
      requestId: "request",
    }),
  );
  await waitFor(() => expect(result.current.transfer.data?.status).toBe("review"));
  await act(() => result.current.apply.mutateAsync({}));
  expect(client.getQueryState(qk.kb.list())?.isInvalidated).toBe(false);
  current = {
    ...row("ready"),
    phase: "apply",
    receipt: {
      roots: { "workflow/root": "new" },
      created: { "knowledge_base/new": "new-kb" },
      reused: {},
      skipped: [],
    },
  };
  await act(() => result.current.transfer.refetch());
  await waitFor(() => expect(client.getQueryState(qk.kb.list())?.isInvalidated).toBe(true));
  expect(applyBundleTransfer).toHaveBeenCalledTimes(1);
});
