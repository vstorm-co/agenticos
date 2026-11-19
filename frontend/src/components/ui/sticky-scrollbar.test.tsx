import { act, fireEvent, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { describe, expect, it } from "vitest";

import { StickyScrollbar } from "./sticky-scrollbar";

const VIEWPORT = window.innerHeight;

/** A target `scrollWidth` wide in a 300px box, its edges at `top` and `bottom`. */
function Harness({
  scrollWidth,
  top,
  bottom,
}: {
  scrollWidth: number;
  top: number;
  bottom: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  return (
    <div>
      <div
        data-testid="target"
        ref={(element) => {
          ref.current = element;
          if (!element) return;
          Object.defineProperty(element, "scrollWidth", { configurable: true, value: scrollWidth });
          Object.defineProperty(element, "clientWidth", { configurable: true, value: 300 });
          element.getBoundingClientRect = () => ({ top, bottom, left: 24 }) as DOMRect;
        }}
      />
      <StickyScrollbar target={ref} />
    </div>
  );
}

const rail = () => document.querySelector<HTMLElement>("[data-sticky-scrollbar]");

describe("StickyScrollbar", () => {
  it("floats at the bottom of the screen while a wide target runs past it", () => {
    render(<Harness scrollWidth={900} top={100} bottom={VIEWPORT + 400} />);

    expect(rail()).toHaveClass("fixed", "bottom-0");
    expect(rail()!.style.left).toBe("24px");
    expect(rail()!.style.width).toBe("300px");
    expect((rail()!.firstElementChild as HTMLElement).style.width).toBe("900px");
  });

  it("scrolls the target sideways, and follows it", () => {
    render(<Harness scrollWidth={900} top={100} bottom={VIEWPORT + 400} />);
    const target = screen.getByTestId("target");

    rail()!.scrollLeft = 120;
    fireEvent.scroll(rail()!);
    expect(target.scrollLeft).toBe(120);

    target.scrollLeft = 40;
    fireEvent.scroll(target);
    expect(rail()!.scrollLeft).toBe(40);
  });

  it("goes away once the target's own bar is on screen", () => {
    const view = render(<Harness scrollWidth={900} top={100} bottom={VIEWPORT + 400} />);
    expect(rail()).not.toBeNull();

    view.rerender(<Harness scrollWidth={900} top={100} bottom={VIEWPORT - 50} />);
    act(() => {
      window.dispatchEvent(new Event("scroll"));
    });
    expect(rail()).toBeNull();
  });

  it("is not drawn for a target that fits its box, or one not yet mounted", () => {
    render(<Harness scrollWidth={300} top={100} bottom={VIEWPORT + 400} />);
    expect(rail()).toBeNull();

    render(<StickyScrollbar target={{ current: null }} />);
    expect(rail()).toBeNull();
  });
});
