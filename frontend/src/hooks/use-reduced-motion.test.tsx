import { act, renderHook } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useMotionStore, type MotionPreference } from "@/stores/motion-store";

import { useReducedMotion } from "./use-reduced-motion";

/** A reduced-motion media query whose answer the test can flip, firing `change`. */
function fakeQuery(initial: boolean) {
  const listeners = new Set<() => void>();
  const query = {
    matches: initial,
    addEventListener: vi.fn((_type: string, listener: () => void) => listeners.add(listener)),
    removeEventListener: vi.fn((_type: string, listener: () => void) => listeners.delete(listener)),
  };
  window.matchMedia = vi.fn().mockReturnValue(query) as unknown as typeof matchMedia;
  return {
    query,
    set(matches: boolean) {
      query.matches = matches;
      listeners.forEach((listener) => listener());
    },
  };
}

const original = window.matchMedia;
beforeEach(() => {
  useMotionStore.setState({ motion: "system" });
});
afterEach(() => {
  window.matchMedia = original;
});

describe("useReducedMotion", () => {
  it.each<[MotionPreference, boolean, boolean]>([
    ["system", false, false],
    ["system", true, true],
    ["reduce", false, true],
    ["reduce", true, true],
    ["full", false, false],
    ["full", true, false],
  ])("%s with the OS asking %s reduces: %s", (preference, os, reduced) => {
    fakeQuery(os);
    useMotionStore.setState({ motion: preference });

    const { result } = renderHook(() => useReducedMotion());

    expect(result.current).toBe(reduced);
  });

  it("follows the operating system changing its mind, while on System", () => {
    const os = fakeQuery(false);
    const { result } = renderHook(() => useReducedMotion());
    expect(result.current).toBe(false);

    act(() => os.set(true));

    expect(result.current).toBe(true);
  });

  it("follows the preference changing, without a reload", () => {
    fakeQuery(false);
    const { result } = renderHook(() => useReducedMotion());

    act(() => useMotionStore.getState().setMotion("reduce"));
    expect(result.current).toBe(true);

    act(() => useMotionStore.getState().setMotion("full"));
    expect(result.current).toBe(false);
  });

  it("stops listening once unmounted", () => {
    const { query } = fakeQuery(false);
    const { unmount } = renderHook(() => useReducedMotion());

    unmount();

    expect(query.removeEventListener).toHaveBeenCalledWith("change", expect.any(Function));
  });

  it("subscribes to the store alone where there is no media query", () => {
    window.matchMedia = undefined as unknown as typeof matchMedia;
    const { result, unmount } = renderHook(() => useReducedMotion());
    expect(result.current).toBe(false);

    act(() => useMotionStore.getState().setMotion("reduce"));
    expect(result.current).toBe(true);
    unmount();
  });

  it("answers false on the server, whatever is stored", () => {
    fakeQuery(true);
    useMotionStore.setState({ motion: "reduce" });

    function Probe() {
      return <span>{String(useReducedMotion())}</span>;
    }

    expect(renderToString(<Probe />)).toContain("false");
  });
});
