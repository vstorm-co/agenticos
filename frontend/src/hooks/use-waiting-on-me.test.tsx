import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Perm, type Permission } from "@/types/permissions";
import { useWaitingOnMe } from "./use-waiting-on-me";

const state = vi.hoisted(() => ({
  granted: new Set<string>(),
  asked: {} as Record<string, unknown>,
  review: 0,
  suites: [] as unknown[],
  waiting: null as unknown,
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (perm: Permission) => state.granted.has(perm) }),
}));
vi.mock("@/hooks/use-scoring", () => ({
  useReviewQueue: (args: unknown) => {
    state.asked.review = args;
    return { total: state.review };
  },
}));
vi.mock("@/hooks/use-eval-suites", () => ({
  useVisibleEvalSuites: (args: unknown) => {
    state.asked.suites = args;
    return { suites: state.suites };
  },
}));
vi.mock("@/hooks/use-authoring", () => ({
  useWaitingSuggestions: (args: unknown) => {
    state.asked.suggestions = args;
    return { waiting: state.waiting };
  },
}));

beforeEach(() => {
  state.granted = new Set([Perm.datasetsView, Perm.runsView, Perm.agentsEdit]);
  state.asked = {};
  state.review = 0;
  state.suites = [];
  state.waiting = null;
});

describe("useWaitingOnMe", () => {
  it("counts answers to review, active suites that failed last, and every suggestion", () => {
    state.review = 9;
    state.suites = [
      { is_active: true, last_result: { status: "failed" } },
      { is_active: false, last_result: { status: "failed" } },
      { is_active: true, last_result: { status: "passed" } },
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

    expect(renderHook(() => useWaitingOnMe()).result.current).toEqual({
      review: 9,
      suites: 1,
      suggestions: 8,
    });
  });

  it("reads each list only with the permission it asks, and counts nothing it did not read", () => {
    state.granted = new Set();

    expect(renderHook(() => useWaitingOnMe()).result.current).toEqual({
      review: 0,
      suites: 0,
      suggestions: 0,
    });
    expect(state.asked).toEqual({
      review: { limit: 1, enabled: false },
      suites: { enabled: false },
      suggestions: { enabled: false },
    });
  });
});
