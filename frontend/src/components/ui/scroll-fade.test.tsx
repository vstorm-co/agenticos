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

  it("marks a body with more below it, and watches the rows that arrive later", async () => {
    function Body({ rows }: { rows: number }) {
      const ref = useRef<HTMLDivElement>(null);
      useScrollFade(ref, "y");
      return (
        <div ref={ref} data-testid="body">
          {Array.from({ length: rows }, (_, index) => (
            <p key={index}>row</p>
          ))}
        </div>
      );
    }
    const { rerender } = render(<Body rows={1} />);
    const body = screen.getByTestId("body");
    const tall = (scroll: number) => {
      Object.defineProperty(body, "scrollTop", { configurable: true, value: scroll });
      Object.defineProperty(body, "clientHeight", { configurable: true, value: 100 });
      Object.defineProperty(body, "scrollHeight", { configurable: true, value: 300 });
    };

    tall(0);
    // A row arriving is a child added, which re-reads the geometry.
    rerender(<Body rows={2} />);
    await act(async () => {});
    expect(body).toHaveAttribute("data-more");

    tall(200);
    act(() => {
      fireEvent.scroll(body);
    });
    expect(body).not.toHaveAttribute("data-more");
  });
});
