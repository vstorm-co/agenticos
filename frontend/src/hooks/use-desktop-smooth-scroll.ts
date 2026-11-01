"use client";

import { useEffect } from "react";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { smoothDesktopWheel } from "@/lib/desktop/smooth-scroll";

export function useDesktopSmoothScroll(enabled: boolean): void {
  const reduce = useReducedMotion();
  useEffect(() => {
    const scroller = document.getElementById("main");
    if (enabled && !reduce && scroller) return smoothDesktopWheel(scroller);
  }, [enabled, reduce]);
}
