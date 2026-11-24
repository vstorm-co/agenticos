import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { NAVIGATION_START, navigationDestination } from "@/lib/navigation-progress";
import { useConsoleRouter } from "./use-console-router";

const native = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  back: vi.fn(),
  forward: vi.fn(),
  refresh: vi.fn(),
  prefetch: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => native }));
afterEach(() => vi.restoreAllMocks());

it("announces imperative route changes while preserving Next options and other router methods", () => {
  window.history.replaceState({}, "", "/chat");
  const events = vi.spyOn(window, "dispatchEvent");
  const { result, rerender } = renderHook(useConsoleRouter);
  const first = result.current;
  act(() => result.current.push("/workflows/runs", { scroll: false }));
  expect(native.push).toHaveBeenCalledWith("/workflows/runs", { scroll: false });
  expect(events.mock.calls[0]?.[0].type).toBe(NAVIGATION_START);
  act(() => result.current.replace("/workflows/one/runs/two"));
  expect(native.replace).toHaveBeenCalledWith("/workflows/one/runs/two");
  expect(events).toHaveBeenCalledTimes(2);
  expect(result.current.back).toBe(native.back);
  expect(result.current.refresh).toBe(native.refresh);
  expect(result.current.prefetch).toBe(native.prefetch);
  rerender();
  expect(result.current).toBe(first);
});

it("does not show route progress for an unchanged address, hash, invalid URL or external destination", () => {
  window.history.replaceState({}, "", "/chat?id=one");
  const events = vi.spyOn(window, "dispatchEvent");
  const { result } = renderHook(useConsoleRouter);
  for (const href of ["/chat?id=one", "#message", "http://[", "https://example.com/chat"])
    act(() => result.current.push(href));
  expect(events).not.toHaveBeenCalled();
  expect(navigationDestination("/chat?id=two")?.search).toBe("?id=two");
});
