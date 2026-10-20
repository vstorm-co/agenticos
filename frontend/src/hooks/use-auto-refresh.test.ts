import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAutoRefresh } from "./use-auto-refresh";

const MINUTE = 60_000;

let visibility: DocumentVisibilityState = "visible";

function setVisibility(next: DocumentVisibilityState) {
  visibility = next;
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

describe("useAutoRefresh", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
    visibility = "visible";
    vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("is off until the viewer picks an interval, then refreshes on it", () => {
    const refresh = vi.fn();
    const { result } = renderHook(() => useAutoRefresh("a1", refresh, false));
    expect(result.current.minutes).toBe(0);
    act(() => vi.advanceTimersByTime(60 * MINUTE));
    expect(refresh).not.toHaveBeenCalled();

    act(() => result.current.setMinutes(5));
    act(() => vi.advanceTimersByTime(5 * MINUTE));
    expect(refresh).toHaveBeenCalledTimes(1);
    act(() => vi.advanceTimersByTime(10 * MINUTE));
    expect(refresh).toHaveBeenCalledTimes(3);
  });

  it("calls the latest refresh it was given", () => {
    const first = vi.fn();
    const second = vi.fn();
    localStorage.setItem("agenticos:artifact-refresh:a1", "1");
    const { rerender } = renderHook(({ refresh }) => useAutoRefresh("a1", refresh, false), {
      initialProps: { refresh: first },
    });
    rerender({ refresh: second });
    act(() => vi.advanceTimersByTime(MINUTE));
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });

  it("remembers the auto-refresh choice per page", () => {
    const { result, unmount } = renderHook(() => useAutoRefresh("a1", vi.fn(), false));
    act(() => result.current.setMinutes(15));
    unmount();

    expect(localStorage.getItem("agenticos:artifact-refresh:a1")).toBe("15");
    expect(renderHook(() => useAutoRefresh("a1", vi.fn(), false)).result.current.minutes).toBe(15);
    expect(renderHook(() => useAutoRefresh("a2", vi.fn(), false)).result.current.minutes).toBe(0);
  });

  it("reads anything it did not write as off", () => {
    localStorage.setItem("agenticos:artifact-refresh:a1", "7");
    expect(renderHook(() => useAutoRefresh("a1", vi.fn(), false)).result.current.minutes).toBe(0);
  });

  it("survives blocked storage", () => {
    vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    const refresh = vi.fn();
    const { result } = renderHook(() => useAutoRefresh("a1", refresh, false));
    expect(result.current.minutes).toBe(0);

    // The choice still holds for as long as the page is open.
    act(() => result.current.setMinutes(1));
    expect(result.current.minutes).toBe(1);
    act(() => vi.advanceTimersByTime(MINUTE));
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("pauses while the tab is hidden and catches up once", () => {
    localStorage.setItem("agenticos:artifact-refresh:a1", "1");
    const refresh = vi.fn();
    renderHook(() => useAutoRefresh("a1", refresh, false));

    setVisibility("hidden");
    act(() => vi.advanceTimersByTime(5 * MINUTE));
    expect(refresh).not.toHaveBeenCalled();

    setVisibility("visible");
    expect(refresh).toHaveBeenCalledTimes(1);
    // Once: coming back again with nothing missed reads nothing more.
    setVisibility("hidden");
    setVisibility("visible");
    expect(refresh).toHaveBeenCalledTimes(1);

    act(() => vi.advanceTimersByTime(MINUTE));
    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it("does not tick while stopped, and starts again once it is not", () => {
    localStorage.setItem("agenticos:artifact-refresh:a1", "1");
    const refresh = vi.fn();
    const { rerender } = renderHook(({ stopped }) => useAutoRefresh("a1", refresh, stopped), {
      initialProps: { stopped: true },
    });
    act(() => vi.advanceTimersByTime(5 * MINUTE));
    setVisibility("hidden");
    setVisibility("visible");
    expect(refresh).not.toHaveBeenCalled();

    rerender({ stopped: false });
    act(() => vi.advanceTimersByTime(MINUTE));
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("stops ticking once the page is left", () => {
    localStorage.setItem("agenticos:artifact-refresh:a1", "1");
    const refresh = vi.fn();
    const { unmount } = renderHook(() => useAutoRefresh("a1", refresh, false));
    unmount();
    act(() => vi.advanceTimersByTime(5 * MINUTE));
    expect(refresh).not.toHaveBeenCalled();
  });
});
