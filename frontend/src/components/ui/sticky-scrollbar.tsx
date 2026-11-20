"use client";

import { useEffect, useRef, useState, type RefObject } from "react";
import { createPortal } from "react-dom";

/** Move `element` sideways to `left`, unless it is there already. */
function scrollSideways(element: HTMLElement | null, left: number): void {
  if (element && element.scrollLeft !== left) element.scrollLeft = left;
}

/** Where the floating bar sits, or null while the target's own bar is in view. */
interface Placement {
  left: number;
  width: number;
  scrollWidth: number;
}

/**
 * A horizontal scrollbar for `target`, floating at the bottom of the viewport.
 *
 * A wide table that grows with the page keeps its own scrollbar under its last
 * row, so moving sideways meant scrolling to the end of the list first. While
 * the target is wider than its box and its bottom edge is below the viewport,
 * this bar is drawn fixed at the bottom of the screen and mirrors the target's
 * horizontal scroll; once the target's own bar comes into view it goes away.
 *
 * Fixed and portalled to `body` rather than `position: sticky`: sticky pins to
 * the nearest scrolling ancestor, and a transformed one captures `fixed`, so
 * either would put the bar back at the bottom of the table on some pages.
 */
export function StickyScrollbar({ target }: { target: RefObject<HTMLElement | null> }) {
  const railRef = useRef<HTMLDivElement>(null);
  const [placement, setPlacement] = useState<Placement | null>(null);

  useEffect(() => {
    const element = target.current;
    if (!element) return;
    const measure = () => {
      const box = element.getBoundingClientRect();
      const overflowing = element.scrollWidth > element.clientWidth + 1;
      const bottomHidden = box.top < window.innerHeight && box.bottom > window.innerHeight;
      setPlacement(
        overflowing && bottomHidden
          ? { left: box.left, width: element.clientWidth, scrollWidth: element.scrollWidth }
          : null,
      );
    };
    const follow = () => {
      const rail = railRef.current;
      if (rail && rail.scrollLeft !== element.scrollLeft) rail.scrollLeft = element.scrollLeft;
    };
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    if (element.firstElementChild) observer.observe(element.firstElementChild);
    measure();
    // Capture: the page scrolls inside the layout's own scroller, not the window.
    window.addEventListener("scroll", measure, { capture: true, passive: true });
    window.addEventListener("resize", measure);
    element.addEventListener("scroll", follow, { passive: true });
    return () => {
      observer.disconnect();
      window.removeEventListener("scroll", measure, { capture: true });
      window.removeEventListener("resize", measure);
      element.removeEventListener("scroll", follow);
    };
  }, [target]);

  // Shown after a scroll: start where the table already is.
  useEffect(() => {
    const element = target.current;
    if (placement && railRef.current && element) railRef.current.scrollLeft = element.scrollLeft;
  }, [placement, target]);

  if (!placement) return null;
  return createPortal(
    <div
      ref={railRef}
      aria-hidden
      data-sticky-scrollbar
      className="bg-card/95 border-border fixed bottom-0 z-40 scrollbar-thin overflow-x-auto overflow-y-hidden border-t backdrop-blur"
      style={{ left: placement.left, width: placement.width }}
      onScroll={(event) => scrollSideways(target.current, event.currentTarget.scrollLeft)}
    >
      <div className="h-px" style={{ width: placement.scrollWidth }} />
    </div>,
    document.body,
  );
}
