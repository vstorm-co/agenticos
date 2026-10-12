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

/** Marks `ref`'s element with `data-more` while it can still scroll right. */
export function useScrollFade(ref: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    const strip = ref.current;
    if (!strip) return;
    const update = () => {
      const more = strip.scrollLeft + strip.clientWidth < strip.scrollWidth - 1;
      strip.toggleAttribute("data-more", more);
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(strip);
    strip.addEventListener("scroll", update, { passive: true });
    return () => {
      observer.disconnect();
      strip.removeEventListener("scroll", update);
    };
  }, [ref]);
}
