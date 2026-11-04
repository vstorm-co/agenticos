import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "@/stores";

import { useBlobbyActivity } from "./use-blobby-activity";

const reads = vi.hoisted(() => ({ approvals: 0, unread: 0, running: 0, runs: vi.fn() }));

vi.mock("@/hooks/use-assistant-signals", () => ({
  useAssistantSignals: () => ({ pendingApprovals: reads.approvals }),
}));
vi.mock("@/hooks/use-notifications", () => ({
  useUnreadNotificationCount: () => ({ count: reads.unread, approximate: false }),
}));
vi.mock("@/hooks/use-runs", () => ({
  useRuns: (...args: unknown[]) => {
    reads.runs(...args);
    return { total: reads.running };
  },
}));

beforeEach(() => {
  Object.assign(reads, { approvals: 0, unread: 0, running: 0 });
  reads.runs.mockClear();
  useAuthStore.setState({ user: { id: "u1" } as never });
});

describe("useBlobbyActivity", () => {
  it("says the most urgent thing about the person's agents", () => {
    Object.assign(reads, { approvals: 1, unread: 4, running: 2 });
    expect(renderHook(() => useBlobbyActivity(true)).result.current).toEqual({
      kind: "approvals",
      count: 1,
    });
  });

  it("counts only the person's own running runs", () => {
    reads.running = 2;
    expect(renderHook(() => useBlobbyActivity(true)).result.current).toEqual({
      kind: "running",
      count: 2,
    });
    expect(reads.runs).toHaveBeenCalledWith(
      undefined,
      expect.objectContaining({ statuses: ["running"], userId: "u1", enabled: true }),
    );
  });

  it("is quiet, and asks for no runs, with nobody signed in", () => {
    reads.approvals = 3;
    useAuthStore.setState({ user: null });
    expect(renderHook(() => useBlobbyActivity(false)).result.current).toEqual({ kind: "quiet" });
    expect(reads.runs).toHaveBeenCalledWith(undefined, expect.objectContaining({ enabled: false }));
  });
});
