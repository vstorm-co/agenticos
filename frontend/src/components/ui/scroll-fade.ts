"use client";

import { useEffect, type RefObject } from "react";

/**
 * A scrolling strip hints at content beyond either edge. `data-more` marks
 * later content and `data-more-start` earlier content, after scrolling.
 *
 * A tab strip wider than a phone scrolls, and cut at the screen's edge mid-word
 * ("Deploym", "Ava") it read as a rendering fault rather than as more to swipe
 * to. The fade is the cue native apps give; it lifts once the end is reached,
 * and a strip that fits never takes it.
 */
export const SCROLL_FADE =
  "scroll-px-8 data-[more-start]:[mask-image:linear-gradient(to_right,transparent,#000_2rem)] data-[more]:[mask-image:linear-gradient(to_right,#000_calc(100%-2rem),transparent)] data-[more-start]:data-[more]:[mask-image:linear-gradient(to_right,transparent,#000_2rem,#000_calc(100%-2rem),transparent)]";

/**
 * The same cue at the bottom edge, for a body that scrolls down: a dashboard
 * card holding more rows than its cell, whose list read as cut off at the
 * border where macOS hides the scrollbar.
 */
export const SCROLL_FADE_Y =
  "data-[more]:[mask-image:linear-gradient(to_bottom,#000_calc(100%-2rem),transparent)]";

/**
 * Marks `ref`'s element with `data-more` while it can still scroll right - or,
 * with `axis` "y", down.
 *
 * Children can arrive or change width without resizing the scrollport itself.
 * Observe them on either axis, releasing removed children as lists refresh.
 */
export function useScrollFade(ref: RefObject<HTMLElement | null>, axis: "x" | "y" = "x"): void {
  useEffect(() => {
    const strip = ref.current;
    if (!strip) return;
    const update = () => {
      const more =
        axis === "x"
          ? strip.scrollLeft + strip.clientWidth < strip.scrollWidth - 1
          : strip.scrollTop + strip.clientHeight < strip.scrollHeight - 1;
      strip.toggleAttribute("data-more", more);
      strip.toggleAttribute("data-more-start", axis === "x" && strip.scrollLeft > 1);
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(strip);
    const watched = new Set<Element>();
    const watchChildren = () => {
      for (const child of watched) {
        if (child.parentElement !== strip) {
          observer.unobserve(child);
          watched.delete(child);
        }
      }
      for (const child of strip.children) {
        if (!watched.has(child)) {
          observer.observe(child);
          watched.add(child);
        }
      }
      update();
    };
    const mutations = new MutationObserver(watchChildren);
    watchChildren();
    mutations.observe(strip, { childList: true });
    strip.addEventListener("scroll", update, { passive: true });
    return () => {
      observer.disconnect();
      mutations.disconnect();
      strip.removeEventListener("scroll", update);
    };
  }, [ref, axis]);
}
