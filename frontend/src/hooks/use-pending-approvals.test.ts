import { renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { usePendingApprovals } from "./use-pending-approvals";

const state = vi.hoisted(() => ({
  allowed: true,
  me: "me" as string | undefined,
  steps: [] as { id: string; approver_user_ids: string[] }[],
  toolsEnabled: [] as (boolean | undefined)[],
  stepsEnabled: [] as (boolean | undefined)[],
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => state.allowed }),
}));
vi.mock("@/stores/auth-store", () => ({
  useAuthStore: (select: (s: { user: { id: string } | null }) => unknown) =>
    select({ user: state.me ? { id: state.me } : null }),
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
    return { approvals: state.steps, total: state.steps.length };
  },
}));

beforeEach(() => {
  state.allowed = true;
  state.me = "me";
  state.steps = [{ id: "s1", approver_user_ids: [] }];
  state.toolsEnabled = [];
  state.stepsEnabled = [];
});

it("counts both queues for somebody who may decide", () => {
  const { result } = renderHook(() => usePendingApprovals());
  expect(result.current.count).toBe(4);
  expect(result.current.tools).toHaveLength(1);
  expect(result.current.steps).toHaveLength(1);
  expect(state.toolsEnabled).toContain(true);
});

it("leaves out a step that names other approvers, and keeps one naming the reader", () => {
  state.steps = [
    { id: "anyone", approver_user_ids: [] },
    { id: "mine", approver_user_ids: ["me", "ann"] },
    { id: "ann's", approver_user_ids: ["ann"] },
  ];
  const { result } = renderHook(() => usePendingApprovals());
  expect(result.current.steps.map((step) => step.id)).toEqual(["anyone", "mine"]);
  expect(result.current.count).toBe(3 + 2);
});

it("keeps no named step while the reader is not known yet", () => {
  state.me = undefined;
  state.steps = [{ id: "mine", approver_user_ids: ["me"] }];
  const { result } = renderHook(() => usePendingApprovals());
  expect(result.current.steps).toEqual([]);
});

it("asks neither queue for somebody who may not decide, and waits on nothing", () => {
  state.allowed = false;
  const { result } = renderHook(() => usePendingApprovals());
  expect(result.current).toEqual({ tools: [], steps: [], count: 0 });
  expect(state.toolsEnabled.every((enabled) => enabled === false)).toBe(true);
  expect(state.stepsEnabled.every((enabled) => enabled === false)).toBe(true);
});
