import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { ApiError } from "@/lib/api-error";
import * as api from "@/lib/tables-api";
import { useTableViewStore } from "@/stores/table-view-store";
import type { RecordRead } from "@/types/tables";

import { UNDO_MS, useDeferredDelete } from "./use-deferred-delete";

vi.mock("@/lib/tables-api", () => ({ deleteRecord: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const record = (id: string, revision = 3) => ({ id, revision }) as RecordRead;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

function undo() {
  const options = vi.mocked(toast.success).mock.calls.at(-1)?.[1] as unknown as {
    action: { onClick: () => void };
  };
  options.action.onClick();
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  useTableViewStore.getState().reset();
});
afterEach(() => vi.useRealTimers());

describe("useDeferredDelete", () => {
  it("hides the records at once and sends the deletes only once the window closes", async () => {
    vi.mocked(api.deleteRecord).mockResolvedValue(undefined);
    const { result } = renderHook(() => useDeferredDelete("t1"), { wrapper });

    act(() => result.current([record("a"), record("b", 7)]));

    expect(useTableViewStore.getState().deleting).toEqual({ a: true, b: true });
    expect(toast.success).toHaveBeenCalledWith(
      "2 records deleted.",
      expect.objectContaining({ duration: UNDO_MS }),
    );
    expect(api.deleteRecord).not.toHaveBeenCalled();

    await act(() => vi.advanceTimersByTimeAsync(UNDO_MS));

    expect(api.deleteRecord).toHaveBeenCalledWith("t1", "a", 3);
    expect(api.deleteRecord).toHaveBeenCalledWith("t1", "b", 7);
    expect(useTableViewStore.getState().deleting).toEqual({});
  });

  it("sends nothing and brings the records back on Undo", async () => {
    const { result } = renderHook(() => useDeferredDelete("t1"), { wrapper });
    act(() => result.current([record("a")]));

    act(() => undo());
    await act(() => vi.advanceTimersByTimeAsync(UNDO_MS));

    expect(api.deleteRecord).not.toHaveBeenCalled();
    expect(useTableViewStore.getState().deleting).toEqual({});
  });

  it("keeps a record changed meanwhile, and says why another delete failed", async () => {
    vi.mocked(api.deleteRecord)
      .mockRejectedValueOnce(
        new ApiError(409, "stale", {
          error: { code: "REVISION_CONFLICT", message: "stale", details: null },
        }),
      )
      .mockRejectedValueOnce(new ApiError(500, "boom", null));
    const { result } = renderHook(() => useDeferredDelete("t1"), { wrapper });
    act(() => result.current([record("a"), record("b")]));

    await act(() => vi.advanceTimersByTimeAsync(UNDO_MS));

    expect(toast.error).toHaveBeenCalledTimes(2);
    expect(useTableViewStore.getState().deleting).toEqual({});
  });
});
