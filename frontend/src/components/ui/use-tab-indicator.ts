"use client";

import { useLayoutEffect, type RefObject } from "react";

/** Share one selection marker; geometry also supports browsers without CSS anchors. */
export function useTabIndicator(ref: RefObject<HTMLElement | null>): void {
  useLayoutEffect(() => {
    const strip = ref.current;
    if (!strip) return;
    const update = () => {
      const active = strip.querySelector<HTMLElement>(
        ':scope > [aria-selected="true"], :scope > [aria-current="page"], :scope > [aria-checked="true"], :scope > [aria-pressed="true"]',
      );
      if (!active || active.offsetWidth === 0) {
        strip.removeAttribute("data-indicator-ready");
        return;
      }
      strip.style.setProperty("--tab-x", `${active.offsetLeft}px`);
      strip.style.setProperty("--tab-y", `${active.offsetTop}px`);
      strip.style.setProperty("--tab-width", `${active.offsetWidth}px`);
      strip.style.setProperty("--tab-height", `${active.offsetHeight}px`);
      strip.setAttribute("data-indicator-ready", "");
    };
    const resize = new ResizeObserver(update);
    const observe = () => {
      resize.disconnect();
      resize.observe(strip);
      for (const child of strip.children) resize.observe(child);
      update();
    };
    const changes = new MutationObserver(observe);
    changes.observe(strip, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["aria-selected", "aria-current", "aria-checked", "aria-pressed"],
    });
    observe();
    return () => {
      resize.disconnect();
      changes.disconnect();
      strip.removeAttribute("data-indicator-ready");
    };
  }, [ref]);
}
