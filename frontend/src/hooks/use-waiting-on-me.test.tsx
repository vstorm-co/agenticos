import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Perm, type Permission } from "@/types/permissions";
import { useWaitingOnMe, waitingOn } from "./use-waiting-on-me";

const state = vi.hoisted(() => ({
  granted: new Set<string>(),
  loaded: true,
  asked: {} as Record<string, unknown>,
  review: [] as unknown[],
  suites: [] as unknown[],
  waiting: null as unknown,
  read: { isLoading: false, error: null as unknown, refetch: (() => {}) as () => void },
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    can: (perm: Permission) => state.granted.has(perm),
    isLoaded: state.loaded,
  }),
}));
vi.mock("@/hooks/use-scoring", () => ({
  useReviewQueue: (args: unknown) => {
    state.asked.review = args;
    return { datasets: state.review, ...state.read };
  },
}));
vi.mock("@/hooks/use-eval-suites", () => ({
  useVisibleEvalSuites: (args: unknown) => {
    state.asked.suites = args;
    return { suites: state.suites, isLoading: false, error: null, refetch: vi.fn() };
  },
}));
vi.mock("@/hooks/use-authoring", () => ({
  useWaitingSuggestions: (args: unknown) => {
    state.asked.suggestions = args;
    return { waiting: state.waiting, isLoading: false, error: null, refetch: vi.fn() };
  },
}));

beforeEach(() => {
  state.granted = new Set([Perm.datasetsView, Perm.runsView, Perm.agentsEdit]);
  state.loaded = true;
  state.read = { isLoading: false, error: null, refetch: vi.fn() };
  state.asked = {};
  state.review = [];
  state.suites = [];
  state.waiting = null;
});

describe("useWaitingOnMe", () => {
  it("counts answers to review, active suites that failed last, and every suggestion", () => {
    state.review = [
      { can_edit: true, failed: 3, unscored: 4, passed: 2 },
      // Seen, and not the reader's to decide.
      { can_edit: false, failed: 5, unscored: 0, passed: 0 },
    ];
    state.suites = [
      { is_active: true, last_result: { status: "failed", alerting: true } },
      { is_active: true, last_result: { status: "error", alerting: true } },
      { is_active: true, last_result: { status: "inconclusive", alerting: true } },
      { is_active: false, last_result: { status: "failed", alerting: true } },
      { is_active: true, last_result: { status: "passed", alerting: false } },
      { is_active: true, last_result: null },
    ];
    state.waiting = {
      agents: [
        { instructions: 2, tools: 1, fields: 1 },
        { instructions: 1, tools: 0 },
      ],
      skills: 1,
      contexts: 2,
    };

    expect(renderHook(() => useWaitingOnMe()).result.current).toMatchObject({
      review: 9,
      suites: 3,
      suggestions: 8,
      settled: true,
      failed: false,
    });
  });

  it("is not settled before the reader's permissions are in", () => {
    // Until then every list is disabled, and a disabled list reads as answered.
    state.loaded = false;
    expect(renderHook(() => useWaitingOnMe()).result.current.settled).toBe(false);
  });

  it("is not settled while a list is loading or after it failed", () => {
    state.read = { isLoading: true, error: null, refetch: vi.fn() };
    const loading = renderHook(() => useWaitingOnMe()).result.current;
    expect(loading.settled).toBe(false);
    expect(loading.failed).toBe(false);

    state.read = { isLoading: false, error: new Error("boom"), refetch: vi.fn() };
    const failed = renderHook(() => useWaitingOnMe()).result.current;
    expect(failed.settled).toBe(false);
    expect(failed.failed).toBe(true);
  });

  it("reads again only the lists that were refused", () => {
    const refused = vi.fn();
    state.read = { isLoading: false, error: new Error("boom"), refetch: refused };

    renderHook(() => useWaitingOnMe()).result.current.retry();

    expect(refused).toHaveBeenCalledOnce();
  });

  it("reads each list only for whoever may act on it, and counts nothing it did not read", () => {
    state.granted = new Set();

    expect(renderHook(() => useWaitingOnMe()).result.current).toMatchObject({
      review: 0,
      suites: 0,
      suggestions: 0,
      settled: true,
      failed: false,
    });
    expect(state.asked).toEqual({
      review: { limit: 1, enabled: false },
      suites: { enabled: false },
      suggestions: { enabled: false },
    });
  });
});

describe("waitingOn", () => {
  it("lists each kind that waits, the tool calls first, and none at zero", () => {
    expect(waitingOn(2, { review: 0, suites: 1, suggestions: 3 })).toEqual([
      ["approvals", 2],
      ["suites", 1],
      ["suggestions", 3],
    ]);
    expect(waitingOn(0, { review: 0, suites: 0, suggestions: 0 })).toEqual([]);
  });
});
