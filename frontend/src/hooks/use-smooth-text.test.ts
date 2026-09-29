import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useLinger, useSmoothText, wordCut } from "./use-smooth-text";

function stubMotion(reduce: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: reduce && query.includes("reduce") }));
}

describe("useSmoothText", () => {
  beforeEach(() => {
    vi.useFakeTimers({
      toFake: [
        "requestAnimationFrame",
        "cancelAnimationFrame",
        "performance",
        "setTimeout",
        "clearTimeout",
      ],
    });
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

  it("shows a conversation reopened mid-turn at once, then paces what arrives after", () => {
    const opening = `${"Already read. ".repeat(30)}`;
    const { result, rerender } = renderHook(({ text }) => useSmoothText(text, true), {
      initialProps: { text: opening },
    });
    expect(result.current).toBe(opening);

    // Ending on a space: a last word with nothing after it may still be arriving,
    // and is held back - see the half-arrived word below.
    const full = `${opening}And this is a longer answer arriving in one burst. `;
    rerender({ text: full });
    expect(result.current).toBe(opening);

    act(() => vi.advanceTimersByTime(100));
    const midway = result.current;
    expect(midway.length).toBeGreaterThan(opening.length);
    expect(midway.length).toBeLessThan(full.length);

    act(() => vi.advanceTimersByTime(3000));
    expect(result.current).toBe(full);
  });

  it("flows a short opening in from nothing", () => {
    // A fast model sends its first sentence as one chunk; showing it whole is the
    // hard edge the reveal exists to take off.
    const { result } = renderHook(() => useSmoothText("Autumn comes early here. ", true));
    expect(result.current).toBe("");

    act(() => vi.advanceTimersByTime(3000));
    expect(result.current).toBe("Autumn comes early here. ");
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

  it("holds a half-arrived word back until the rest of it lands", () => {
    const { result, rerender } = renderHook(({ text }) => useSmoothText(text, true), {
      initialProps: { text: "" },
    });
    rerender({ text: "Streaming answers arrive in pie" });
    act(() => vi.advanceTimersByTime(3000));
    // `pie` may be the start of `pieces`; showing it now would let the rest of the
    // word appear without its fade.
    expect(result.current).toBe("Streaming answers arrive in ");

    rerender({ text: "Streaming answers arrive in pieces." });
    act(() => vi.advanceTimersByTime(3000));
    expect(result.current).toBe("Streaming answers arrive in ");

    rerender({ text: "Streaming answers arrive in pieces. " });
    act(() => vi.advanceTimersByTime(3000));
    expect(result.current).toBe("Streaming answers arrive in pieces. ");
  });

  it("starts over from a shorter text in the same slot", () => {
    const { result, rerender } = renderHook(({ text }) => useSmoothText(text, true), {
      initialProps: { text: "A long first message. ".repeat(20) },
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

describe("wordCut", () => {
  it("moves a cut inside a word to the end of that word", () => {
    expect(wordCut("one two three", 5, false)).toBe(7);
  });

  it("leaves a cut already on a space where it is", () => {
    expect(wordCut("one two", 3, true)).toBe(3);
  });

  it("stops before the last word while it may still be arriving", () => {
    expect(wordCut("one tw", 5, true)).toBe(4);
  });

  it("shows the last word once the text is final", () => {
    expect(wordCut("one tw", 5, false)).toBe(6);
  });

  it("does not wait on a run too long to be a word", () => {
    // A URL, or a script written without spaces: it is revealed in steps rather
    // than held back until whitespace that may never come.
    const unbroken = "文字文字文字文字文字文字文字文字文字文字";
    expect(wordCut(unbroken, 2, true)).toBe(18);
    expect(wordCut(unbroken, 18, true)).toBe(unbroken.length);
  });
});

describe("useLinger", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("stays on for the given time after its cause ends", () => {
    const { result, rerender } = renderHook(({ active }) => useLinger(active, 700), {
      initialProps: { active: true },
    });
    rerender({ active: false });
    expect(result.current).toBe(true);

    act(() => vi.advanceTimersByTime(699));
    expect(result.current).toBe(true);
    act(() => vi.advanceTimersByTime(1));
    expect(result.current).toBe(false);
  });

  it("starts the wait over when its cause returns and ends again", () => {
    const { result, rerender } = renderHook(({ active }) => useLinger(active, 700), {
      initialProps: { active: true },
    });
    rerender({ active: false });
    act(() => vi.advanceTimersByTime(500));
    rerender({ active: true });
    rerender({ active: false });

    act(() => vi.advanceTimersByTime(500));
    expect(result.current).toBe(true);
    act(() => vi.advanceTimersByTime(200));
    expect(result.current).toBe(false);
  });

  it("is off from the start when its cause never began", () => {
    const { result } = renderHook(() => useLinger(false, 700));

    expect(result.current).toBe(false);
  });
});
