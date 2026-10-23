"use client";

import { useEffect, type RefObject } from "react";

/**
 * The class a sideways-scrolling strip takes so its right edge fades while
 * there is more past it - set by `useScrollFade` as `data-more`.
 *
 * A tab strip wider than a phone scrolls, and cut at the screen's edge mid-word
 * ("Deploym", "Ava") it read as a rendering fault rather than as more to swipe
 * to. The fade is the cue native apps give; it lifts once the end is reached,
 * and a strip that fits never takes it.
 */
export const SCROLL_FADE =
  "data-[more]:[mask-image:linear-gradient(to_right,#000_calc(100%-2rem),transparent)]";

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
 * Downwards the content is what grows, not the box: rows arrive after the
 * card has its height. So for "y" the children are watched as well, and a
 * child added later is watched once it arrives.
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
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(strip);
    const watchChildren = () => {
      for (const child of strip.children) observer.observe(child);
      update();
    };
    const mutations = axis === "y" ? new MutationObserver(watchChildren) : null;
    if (mutations) {
      watchChildren();
      mutations.observe(strip, { childList: true });
    }
    strip.addEventListener("scroll", update, { passive: true });
    return () => {
      observer.disconnect();
      mutations?.disconnect();
      strip.removeEventListener("scroll", update);
    };
  }, [ref, axis]);
}
