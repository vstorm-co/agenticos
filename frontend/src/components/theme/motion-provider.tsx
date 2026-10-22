"use client";

import { MotionConfig } from "motion/react";
import { useEffect, type ReactNode } from "react";

import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { prefersReducedMotion } from "@/lib/motion";
import { MOTION_ATTRIBUTE } from "@/lib/motion-preference";

/**
 * Applies the person's Motion preference to the whole app, in both dialects.
 *
 * CSS: `data-motion="reduce"` on `<html>`, which every reduced-motion rule and
 * the `motion-reduce:` / `motion-safe:` variants in `globals.css` key off - so
 * Full overrides the operating system and Reduce works without it. The root
 * layout's inline script sets it before the first paint; this keeps it current.
 *
 * motion/react: a `MotionConfig` that reduces every animation it drives (or
 * none), where motion's default would follow only the operating system.
 *
 * The attribute is written from `prefersReducedMotion()` rather than from the
 * hook's value: through hydration the hook answers `false` (the server's
 * answer), and writing that would strip the attribute the inline script just
 * set, for a frame, from somebody who asked for no motion.
 */
export function MotionProvider({ children }: { children: ReactNode }) {
  const reduced = useReducedMotion();

  useEffect(() => {
    const root = document.documentElement;
    if (prefersReducedMotion()) root.setAttribute(MOTION_ATTRIBUTE, "reduce");
    else root.removeAttribute(MOTION_ATTRIBUTE);
  }, [reduced]);

  return <MotionConfig reducedMotion={reduced ? "always" : "never"}>{children}</MotionConfig>;
}
