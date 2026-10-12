import { act, fireEvent, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { describe, expect, it } from "vitest";

import { useScrollFade } from "./scroll-fade";

function Strip() {
  const ref = useRef<HTMLDivElement>(null);
  useScrollFade(ref);
  return <div ref={ref} data-testid="strip" />;
}

/** Sets the geometry jsdom never computes, as a browser would report it. */
function measure(strip: HTMLElement, { scroll, width, content }: Record<string, number>) {
  Object.defineProperty(strip, "scrollLeft", { configurable: true, value: scroll });
  Object.defineProperty(strip, "clientWidth", { configurable: true, value: width });
  Object.defineProperty(strip, "scrollWidth", { configurable: true, value: content });
}

/**
 * A strip wider than its box says so at the right edge until it is scrolled
 * to the end, and a strip that fits never does.
 */
describe("useScrollFade", () => {
  it("marks a strip with more past its right edge, and clears it at the end", () => {
    render(<Strip />);
    const strip = screen.getByTestId("strip");

    measure(strip, { scroll: 0, width: 300, content: 500 });
    act(() => {
      fireEvent.scroll(strip);
    });
    expect(strip).toHaveAttribute("data-more");

    measure(strip, { scroll: 200, width: 300, content: 500 });
    act(() => {
      fireEvent.scroll(strip);
    });
    expect(strip).not.toHaveAttribute("data-more");
  });

  it("leaves a strip that fits unmarked", () => {
    render(<Strip />);

    expect(screen.getByTestId("strip")).not.toHaveAttribute("data-more");
  });

  it("does nothing for a strip that was never drawn", () => {
    function Absent() {
      const ref = useRef<HTMLDivElement>(null);
      useScrollFade(ref);
      return null;
    }
    const { container } = render(<Absent />);

    expect(container).toBeEmptyDOMElement();
  });

  it("stops listening once the strip is gone", () => {
    const { unmount } = render(<Strip />);
    unmount();

    expect(screen.queryByTestId("strip")).toBeNull();
  });
});
