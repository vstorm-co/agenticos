import { fireEvent, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { describe, expect, it } from "vitest";

import { useReaderScrolledUp } from "./use-reader-scrolled-up";

const state = { current: false };

function Scroller({ attach = true }: { attach?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useReaderScrolledUp(ref, state);
  return attach ? <div ref={ref} data-testid="scroller" /> : null;
}

/** The geometry jsdom never computes, as a browser would report it. */
function at(element: HTMLElement, fromFoot: number) {
  Object.defineProperty(element, "scrollHeight", { configurable: true, value: 2000 });
  Object.defineProperty(element, "clientHeight", { configurable: true, value: 500 });
  Object.defineProperty(element, "scrollTop", { configurable: true, value: 1500 - fromFoot });
  fireEvent.scroll(element);
}

function mount() {
  state.current = false;
  render(<Scroller />);
  return screen.getByTestId("scroller");
}

/**
 * A reader scrolling up while an answer streams is left where they went - any
 * move up lets go, however small - and following resumes at the foot.
 */
describe("useReaderScrolledUp", () => {
  it("lets go on a wheel turned up, however little, and not on one turned down", () => {
    const scroller = mount();

    fireEvent.wheel(scroller, { deltaY: 40 });
    expect(state.current).toBe(false);
    fireEvent.wheel(scroller, { deltaY: -20 });
    expect(state.current).toBe(true);
  });

  it("lets go on a finger dragging the page down, and not up", () => {
    const scroller = mount();

    fireEvent.touchStart(scroller, { touches: [{ clientY: 300 }] });
    fireEvent.touchMove(scroller, { touches: [{ clientY: 250 }] });
    expect(state.current).toBe(false);
    fireEvent.touchMove(scroller, { touches: [{ clientY: 340 }] });
    expect(state.current).toBe(true);
  });

  it("lets go on the keys that move up", () => {
    const scroller = mount();

    fireEvent.keyDown(scroller, { key: "End" });
    expect(state.current).toBe(false);
    fireEvent.keyDown(scroller, { key: "PageUp" });
    expect(state.current).toBe(true);
  });

  it("follows again at the foot, and lets go of a scrollbar dragged far up", () => {
    const scroller = mount();

    at(scroller, 600);
    expect(state.current).toBe(true);
    at(scroller, 100);
    expect(state.current).toBe(true);
    at(scroller, 10);
    expect(state.current).toBe(false);
  });

  it("ignores a move with no touch it started from", () => {
    const scroller = mount();

    fireEvent.touchMove(scroller, { touches: [{ clientY: 340 }] });

    expect(state.current).toBe(false);
  });

  it("does nothing without a scroller, and stops listening once it is gone", () => {
    state.current = false;
    render(<Scroller attach={false} />).unmount();
    const { unmount } = render(<Scroller />);
    unmount();

    expect(state.current).toBe(false);
  });
});
