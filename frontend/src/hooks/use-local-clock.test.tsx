import { act, renderHook } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, expect, it, vi } from "vitest";
import { useLocalClock } from "./use-local-clock";

afterEach(() => vi.useRealTimers());

it("crosses midnight at the minute boundary and catches up when the tab wakes", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-20T23:59:45Z"));
  const { result, unmount } = renderHook(useLocalClock);
  expect(result.current?.toISOString()).toBe("2026-11-20T23:59:00.000Z");
  act(() => vi.advanceTimersByTime(15_000));
  expect(result.current?.toISOString()).toBe("2026-11-21T00:00:00.000Z");
  act(() => {
    vi.setSystemTime(new Date("2026-11-21T06:42:12Z"));
    document.dispatchEvent(new Event("visibilitychange"));
  });
  expect(result.current?.toISOString()).toBe("2026-11-21T06:42:00.000Z");
  act(() => vi.advanceTimersByTime(48_000));
  expect(result.current?.toISOString()).toBe("2026-11-21T06:43:00.000Z");
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});

it("keeps the server render independent of the server's local date", () => {
  function Clock() {
    return <span>{useLocalClock()?.toISOString() ?? "hydrating"}</span>;
  }
  expect(renderToString(<Clock />)).toBe("<span>hydrating</span>");
});
