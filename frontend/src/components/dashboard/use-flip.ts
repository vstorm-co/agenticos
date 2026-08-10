"use client";

import { type RefObject, useLayoutEffect, useRef } from "react";

/** How long a card takes to glide to its new place, and on what curve. */
const FLIP_TRANSITION = "transform 220ms cubic-bezier(0.2, 0, 0, 1)";

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * FLIP: glide grid children to their new positions after a layout change,
 * instead of snapping. Children opt in with a stable `data-flip-id`; the hook
 * remembers where each sat, and after React commits a new arrangement it offsets
 * every moved child by the inverse of how far it travelled, then releases the
 * offset on the next frame so the browser animates it home.
 *
 * Position only, on purpose: a card the person is resizing changes size at once
 * while its displaced neighbours slide — that sliding is the motion that reads as
 * smooth, and animating a card's own width would fight the pointer that is
 * dragging it. Re-run it by changing `signature` whenever the rendered order or
 * any card's size changes.
 *
 * It is inert in three cases, each a deliberate no-op rather than a guard that
 * throws: reduced-motion (no offset is applied), the first commit (nothing to
 * animate from), and an unmeasured layout — SSR and jsdom report every rect at
 * the origin, so deltas are zero and nothing moves.
 */
export function useFlip<T extends HTMLElement>(signature: string): RefObject<T | null> {
  const containerRef = useRef<T>(null);
  const positions = useRef<Map<string, { left: number; top: number }>>(new Map());

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const reduce = prefersReducedMotion();
    const children = Array.from(container.querySelectorAll<HTMLElement>("[data-flip-id]"));
    const next = new Map<string, { left: number; top: number }>();

    // Positions are measured relative to the FLIP container, not the viewport.
    // The dashboard scrolls an inner overflow-auto <main>, not the window, so a
    // viewport rect shifts by that container's scroll between two commits — and
    // window.scrollY, which tracks the document, stays 0 and cannot cancel it.
    // Subtracting the container's own rect does: child and container move
    // together under any scroll, so only a real layout move changes a child's
    // offset within the container. Without this, the first resize or drag in a
    // section the person had scrolled to translated every card by the scroll
    // distance and glided it back — the jump-up-then-settle they saw.
    const base = container.getBoundingClientRect();

    for (const child of children) {
      const id = child.dataset.flipId;
      if (!id) continue;
      const rect = child.getBoundingClientRect();
      const left = rect.left - base.left;
      const top = rect.top - base.top;
      next.set(id, { left, top });

      const previous = positions.current.get(id);
      if (!previous || reduce) continue;
      const dx = previous.left - left;
      const dy = previous.top - top;
      if (dx === 0 && dy === 0) continue;

      child.style.transition = "none";
      child.style.transform = `translate(${dx}px, ${dy}px)`;
      // Commit the inverted offset before scheduling the release, so the browser
      // has a "from" frame to animate out of rather than collapsing both writes.
      void child.offsetWidth;
      requestAnimationFrame(() => {
        child.style.transition = FLIP_TRANSITION;
        child.style.transform = "";
      });
    }

    positions.current = next;
  }, [signature]);

  return containerRef;
}
