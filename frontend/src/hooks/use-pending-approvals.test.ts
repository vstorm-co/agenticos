import { renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { usePendingApprovals } from "./use-pending-approvals";

const state = vi.hoisted(() => ({
  allowed: true,
  toolsEnabled: [] as (boolean | undefined)[],
  stepsEnabled: [] as (boolean | undefined)[],
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => state.allowed }),
}));
vi.mock("@/hooks/use-runs", () => ({
  useApprovals: (options?: { enabled?: boolean }) => {
    state.toolsEnabled.push(options?.enabled);
    return { approvals: [{ id: "t1" }], total: 3 };
  },
}));
vi.mock("@/hooks/use-workflow-approvals", () => ({
  useWorkflowApprovals: (options?: { enabled?: boolean }) => {
    state.stepsEnabled.push(options?.enabled);
    return { approvals: [{ id: "s1" }], total: 2 };
  },
}));

beforeEach(() => {
  state.allowed = true;
  state.toolsEnabled = [];
  state.stepsEnabled = [];
});

it("counts both queues for somebody who may decide", () => {
  const { result } = renderHook(() => usePendingApprovals());
  expect(result.current.count).toBe(5);
  expect(result.current.tools).toHaveLength(1);
  expect(result.current.steps).toHaveLength(1);
  expect(state.toolsEnabled).toContain(true);
});

it("asks neither queue for somebody who may not decide, and waits on nothing", () => {
  state.allowed = false;
  const { result } = renderHook(() => usePendingApprovals());
  expect(result.current).toEqual({ tools: [], steps: [], count: 0 });
  expect(state.toolsEnabled.every((enabled) => enabled === false)).toBe(true);
  expect(state.stepsEnabled.every((enabled) => enabled === false)).toBe(true);
});
