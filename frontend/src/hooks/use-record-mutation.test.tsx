import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { isRevisionConflict, useRecordMutation } from "./use-record-mutation";
import { apiClient, ApiError } from "@/lib/api-client";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: (...args: unknown[]) => toastError(...args) },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("isRevisionConflict", () => {
  it("is true only for a 409 REVISION_CONFLICT ApiError", () => {
    const conflict = new ApiError(409, "stale", {
      error: { code: "REVISION_CONFLICT", message: "stale", details: null },
    });
    expect(isRevisionConflict(conflict)).toBe(true);
    expect(
      isRevisionConflict(
        new ApiError(409, "taken", {
          error: { code: "ALREADY_EXISTS", message: "taken", details: null },
        }),
      ),
    ).toBe(false);
    expect(isRevisionConflict(new Error("boom"))).toBe(false);
    expect(isRevisionConflict("not an error")).toBe(false);
  });
});

describe("useRecordMutation", () => {
  it("creates a record and toasts on failure", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new ApiError(422, "invalid"));
    const { result } = renderHook(() => useRecordMutation("t1"), { wrapper });

    result.current.create.mutate({ values: {} });

    await waitFor(() => expect(result.current.create.isError).toBe(true));
    expect(toastError).toHaveBeenCalled();
  });

  it("creates a record successfully", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "r1", revision: 1 });
    const { result } = renderHook(() => useRecordMutation("t1"), { wrapper });

    result.current.create.mutate({ values: { c1: "Ada" } });

    await waitFor(() => expect(result.current.create.isSuccess).toBe(true));
    expect(toastError).not.toHaveBeenCalled();
  });

  it("updates a record successfully", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue({ id: "r1", revision: 2 });
    const { result } = renderHook(() => useRecordMutation("t1"), { wrapper });

    result.current.update.mutate({
      recordId: "r1",
      data: { expected_revision: 1, values: { c1: "x" } },
    });

    await waitFor(() => expect(result.current.update.isSuccess).toBe(true));
  });

  it("does not toast a revision conflict on update - the caller shows it inline", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(
      new ApiError(409, "stale", {
        error: { code: "REVISION_CONFLICT", message: "stale", details: null },
      }),
    );
    const { result } = renderHook(() => useRecordMutation("t1"), { wrapper });

    result.current.update.mutate({
      recordId: "r1",
      data: { expected_revision: 1, values: { c1: "x" } },
    });

    await waitFor(() => expect(result.current.update.isError).toBe(true));
    expect(toastError).not.toHaveBeenCalled();
  });

  it("toasts a non-conflict update failure", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new ApiError(422, "invalid"));
    const { result } = renderHook(() => useRecordMutation("t1"), { wrapper });

    result.current.update.mutate({
      recordId: "r1",
      data: { expected_revision: 1, values: {} },
    });

    await waitFor(() => expect(result.current.update.isError).toBe(true));
    expect(toastError).toHaveBeenCalled();
  });

  it("deletes a record successfully", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const { result } = renderHook(() => useRecordMutation("t1"), { wrapper });

    result.current.remove.mutate({ recordId: "r1", expectedRevision: 1 });

    await waitFor(() => expect(result.current.remove.isSuccess).toBe(true));
  });

  it("does not toast a revision conflict on delete", async () => {
    vi.mocked(apiClient.delete).mockRejectedValue(
      new ApiError(409, "stale", {
        error: { code: "REVISION_CONFLICT", message: "stale", details: null },
      }),
    );
    const { result } = renderHook(() => useRecordMutation("t1"), { wrapper });

    result.current.remove.mutate({ recordId: "r1", expectedRevision: 1 });

    await waitFor(() => expect(result.current.remove.isError).toBe(true));
    expect(toastError).not.toHaveBeenCalled();
  });

  it("toasts a non-conflict delete failure", async () => {
    vi.mocked(apiClient.delete).mockRejectedValue(new ApiError(409, "archived table"));
    const { result } = renderHook(() => useRecordMutation("t1"), { wrapper });

    result.current.remove.mutate({ recordId: "r1", expectedRevision: 1 });

    await waitFor(() => expect(result.current.remove.isError).toBe(true));
    expect(toastError).toHaveBeenCalled();
  });
});
