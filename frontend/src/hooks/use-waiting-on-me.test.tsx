import { renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useWaitingOnMe, waitingOn } from "./use-waiting-on-me";

const state = vi.hoisted(() => ({
  allowed: true,
  loaded: true,
  suggestions: [{ id: "proposal" }],
  isLoading: false,
  error: null as Error | null,
  refetch: vi.fn(),
  enabled: vi.fn(),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => state.allowed, isLoaded: state.loaded }),
}));
vi.mock("@/hooks/use-suggestions", () => ({
  useSuggestions: (enabled: boolean) => {
    state.enabled(enabled);
    return state;
  },
}));
beforeEach(() => {
  state.allowed = true;
  state.loaded = true;
  state.isLoading = false;
  state.error = null;
  state.suggestions = [{ id: "proposal" }];
  vi.clearAllMocks();
});
it("counts the reader's open Inbox proposals", () => {
  expect(renderHook(useWaitingOnMe).result.current).toMatchObject({
    suggestions: 1,
    settled: true,
    failed: false,
  });
});
it("does not read proposals without permission or count cached proposals", () => {
  state.allowed = false;
  expect(renderHook(useWaitingOnMe).result.current).toMatchObject({
    suggestions: 0,
    settled: true,
    failed: false,
  });
  expect(state.enabled).toHaveBeenCalledWith(false);
});
it("waits for permissions and the personal Inbox", () => {
  state.loaded = false;
  expect(renderHook(useWaitingOnMe).result.current.settled).toBe(false);
  state.loaded = true;
  state.isLoading = true;
  expect(renderHook(useWaitingOnMe).result.current.settled).toBe(false);
});
it("keeps a failed read explicit and retries it", () => {
  state.error = new Error("offline");
  const { result } = renderHook(useWaitingOnMe);
  expect(result.current).toMatchObject({ settled: false, failed: true });
  result.current.retry();
  expect(state.refetch).toHaveBeenCalledOnce();
});
it("does not retry a successful read", () => {
  renderHook(useWaitingOnMe).result.current.retry();
  expect(state.refetch).not.toHaveBeenCalled();
});
it("lists only personal approvals and proposals, omitting zero counts", () => {
  expect(waitingOn(2, { suggestions: 3 })).toEqual([
    ["approvals", 2],
    ["suggestions", 3],
  ]);
  expect(waitingOn(0, { suggestions: 0 })).toEqual([]);
});
