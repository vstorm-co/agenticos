"use client";

import { useEffect, useRef, type RefObject } from "react";

import { useReducedMotion } from "@/hooks/use-reduced-motion";

/** A new credential refusal shakes the existing field without resetting focus or input. */
export function useRejectedFieldMotion(attempt: number): RefObject<HTMLInputElement | null> {
  const ref = useRef<HTMLInputElement>(null);
  const reduced = useReducedMotion();
  useEffect(() => {
    const input = ref.current;
    if (attempt === 0 || reduced || !input || typeof input.animate !== "function") return;
    const animation = input.animate(
      [0, -10, 10, -6, 6, -3, 0].map((x) => ({ transform: `translateX(${x}px)` })),
      { duration: 360, easing: "ease-out" },
    );
    return () => animation.cancel();
  }, [attempt, reduced]);
  return ref;
}
