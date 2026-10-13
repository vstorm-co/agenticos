import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useFollowContent } from "./use-follow-content";

/** Captures the observer so a test can say when the content grew. */
function installObserver() {
  const seen: { grew?: () => void; observed?: Element; disconnected: boolean } = {
    disconnected: false,
  };
  class FakeResize {
    constructor(callback: () => void) {
      seen.grew = callback;
    }
    observe(element: Element) {
      seen.observed = element;
    }
    disconnect() {
      seen.disconnected = true;
    }
  }
  vi.stubGlobal("ResizeObserver", FakeResize);
  return seen;
}

function scroller(): HTMLElement {
  const element = document.createElement("div");
  Object.defineProperty(element, "scrollHeight", { value: 900 });
  return element;
}

describe("useFollowContent", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("pins the scroller to its bottom whenever the content grows", () => {
    const seen = installObserver();
    const scrolling = scroller();
    const content = document.createElement("div");

    const { unmount } = renderHook(() =>
      useFollowContent({ current: scrolling }, { current: content }),
    );
    expect(seen.observed).toBe(content);

    seen.grew?.();
    expect(scrolling.scrollTop).toBe(900);

    unmount();
    expect(seen.disconnected).toBe(true);
  });

  it("leaves a reader who scrolled up where they are", () => {
    const seen = installObserver();
    const scrolling = scroller();

    renderHook(() =>
      useFollowContent(
        { current: scrolling },
        { current: document.createElement("div") },
        { current: true },
      ),
    );
    seen.grew?.();

    expect(scrolling.scrollTop).toBe(0);
  });

  it("does nothing without the elements or an observer to watch them", () => {
    const seen = installObserver();
    renderHook(() => useFollowContent({ current: null }, { current: null }));
    expect(seen.observed).toBeUndefined();

    vi.stubGlobal("ResizeObserver", undefined);
    expect(() =>
      renderHook(() =>
        useFollowContent({ current: scroller() }, { current: document.createElement("div") }),
      ),
    ).not.toThrow();
  });
});
