import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSmoothText } from "./use-smooth-text";

function stubMotion(reduce: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: reduce && query.includes("reduce") }));
}

describe("useSmoothText", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["requestAnimationFrame", "cancelAnimationFrame", "performance"] });
    stubMotion(false);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("shows a finished message whole", () => {
    const { result } = renderHook(() => useSmoothText("All done.", false));

    expect(result.current).toBe("All done.");
  });

  it("shows what arrived before it mounted, then paces what arrives after", () => {
    const { result, rerender } = renderHook(({ text }) => useSmoothText(text, true), {
      initialProps: { text: "Hello" },
    });
    expect(result.current).toBe("Hello");

    rerender({ text: "Hello, this is a longer answer arriving in one burst." });
    expect(result.current).toBe("Hello");

    act(() => vi.advanceTimersByTime(100));
    const midway = result.current;
    expect(midway.length).toBeGreaterThan("Hello".length);
    expect(midway.length).toBeLessThan(52);

    act(() => vi.advanceTimersByTime(3000));
    expect(result.current).toBe("Hello, this is a longer answer arriving in one burst.");
  });

  it("finishes the reveal after the turn ends, rather than jumping", () => {
    const { result, rerender } = renderHook(
      ({ text, streaming }) => useSmoothText(text, streaming),
      {
        initialProps: { text: "", streaming: true },
      },
    );
    rerender({ text: "The rest of the answer.", streaming: false });
    expect(result.current).toBe("");

    act(() => vi.advanceTimersByTime(3000));
    expect(result.current).toBe("The rest of the answer.");
  });

  it("never cuts an emoji in half", () => {
    const text = "😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀😀";
    const { result, rerender } = renderHook(({ value }) => useSmoothText(value, true), {
      initialProps: { value: "" },
    });
    rerender({ value: text });

    for (let frame = 0; frame < 60; frame += 1) {
      act(() => vi.advanceTimersByTime(40));
      const last = result.current.charCodeAt(result.current.length - 1);
      expect(last >= 0xd800 && last <= 0xdbff).toBe(false);
    }
    expect(result.current).toBe(text);
  });

  it("starts over from a shorter text in the same slot", () => {
    const { result, rerender } = renderHook(({ text }) => useSmoothText(text, true), {
      initialProps: { text: "A long first message" },
    });
    rerender({ text: "New" });

    expect(result.current).toBe("New");
  });

  it("gives the text as it arrives to anyone who asked for less motion", () => {
    stubMotion(true);
    const { result, rerender } = renderHook(({ text }) => useSmoothText(text, true), {
      initialProps: { text: "" },
    });
    rerender({ text: "Straight away." });

    expect(result.current).toBe("Straight away.");
  });
});
