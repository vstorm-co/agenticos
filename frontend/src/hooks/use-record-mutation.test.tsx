import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import type { RecordRead } from "@/types/tables";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { isRecordGone, isRevisionConflict, useRecordMutation } from "./use-record-mutation";
import { apiClient, ApiError } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
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

describe("isRecordGone", () => {
  it("is true only for a 404 ApiError", () => {
    expect(isRecordGone(new ApiError(404, "gone"))).toBe(true);
    expect(isRecordGone(new ApiError(409, "stale"))).toBe(false);
    expect(isRecordGone(new Error("boom"))).toBe(false);
  });
});

function recordAt(revision: number): RecordRead {
  return {
    id: "r1",
    table_id: "t1",
    external_id: null,
    schema_version: 1,
    values: {},
    revision,
    created_at: "2026-09-23T00:00:00Z",
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("useRecordMutation().commit", () => {
  it("sends a second write to one record only once the first answered, against its revision", async () => {
    const first = deferred<RecordRead>();
    vi.mocked(apiClient.patch)
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce(recordAt(3));
    const { result } = renderHook(() => useRecordMutation("t1"), { wrapper });

    const a = result.current.commit(recordAt(1), { c1: "a" });
    const b = result.current.commit(recordAt(1), { c2: "b" });
    await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(1));
    first.resolve(recordAt(2));

    await expect(a).resolves.toEqual(recordAt(2));
    await expect(b).resolves.toEqual(recordAt(3));
    expect(vi.mocked(apiClient.patch).mock.calls[1]).toEqual([
      "/tables/t1/records/r1",
      { expected_revision: 2, values: { c2: "b" } },
    ]);
  });

  it("a refused write rejects its own call and does not hold up the next one", async () => {
    vi.mocked(apiClient.patch)
      .mockRejectedValueOnce(new ApiError(409, "stale"))
      .mockResolvedValueOnce(recordAt(2));
    const { result } = renderHook(() => useRecordMutation("t1"), { wrapper });

    const a = result.current.commit(recordAt(1), { c1: "a" });
    const b = result.current.commit(recordAt(1), { c1: "b" });

    await expect(a).rejects.toBeInstanceOf(ApiError);
    await expect(b).resolves.toEqual(recordAt(2));
    expect(vi.mocked(apiClient.patch).mock.calls[1]?.[1]).toEqual({
      expected_revision: 1,
      values: { c1: "b" },
    });
  });

  it("takes a caller's newer revision over the one its own last write returned", async () => {
    vi.mocked(apiClient.patch)
      .mockResolvedValueOnce(recordAt(2))
      .mockResolvedValueOnce(recordAt(9));
    const { result } = renderHook(() => useRecordMutation("t1"), { wrapper });

    await result.current.commit(recordAt(1), { c1: "a" });
    await result.current.commit(recordAt(8), { c1: "b" });

    expect(vi.mocked(apiClient.patch).mock.calls[1]?.[1]).toEqual({
      expected_revision: 8,
      values: { c1: "b" },
    });
  });

  it("refetches the table's records after a write, and not the table, its views or its schema versions", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue(recordAt(2));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const seeded = [
      qk.tables.detail("t1"),
      qk.tables.views("t1"),
      qk.tables.schemaVersions("t1"),
      qk.tables.records("t1", { skip: 0 }),
    ];
    for (const key of seeded) client.setQueryData(key, { seeded: true });
    const { result } = renderHook(() => useRecordMutation("t1"), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    });

    await result.current.commit(recordAt(1), { c1: "a" });

    await waitFor(() =>
      expect(client.getQueryState(qk.tables.records("t1", { skip: 0 }))?.isInvalidated).toBe(true),
    );
    for (const key of seeded.slice(0, 3)) {
      expect(client.getQueryState(key)?.isInvalidated).toBe(false);
    }
  });
});

describe("useRecordMutation().fetchRecord", () => {
  it("reads the record fresh, every time it is asked", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce(recordAt(4)).mockResolvedValueOnce(recordAt(5));
    const { result } = renderHook(() => useRecordMutation("t1"), { wrapper });

    await expect(result.current.fetchRecord("r1")).resolves.toEqual(recordAt(4));
    await expect(result.current.fetchRecord("r1")).resolves.toEqual(recordAt(5));
    expect(apiClient.get).toHaveBeenCalledWith("/tables/t1/records/r1");
  });
});
