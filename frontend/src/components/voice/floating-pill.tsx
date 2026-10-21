"use client";

import { AnimatePresence, motion } from "motion/react";
import type { ReactNode } from "react";

import { useReducedMotion } from "@/hooks/use-reduced-motion";

/**
 * How a pill moves: a quick, damped spring - it arrives in about 200 ms and
 * settles without a bounce, the way the system's own floating controls do. A
 * linear fade read as a lag; an overshoot read as a toy.
 */
export const PILL_SPRING = { type: "spring", stiffness: 520, damping: 40, mass: 0.7 } as const;

/** What floats above the composer, and which one it is - a new `key` swaps it. */
export interface FloatingPillContent {
  key: string;
  node: ReactNode;
}

/**
 * The slot above `/chat`'s composer where a call's or a dictation's pill floats
 * (#54). It rises in from just below with a slight scale, leaves the same way,
 * and one pill gives way to another - a dictation to a call - by crossing over
 * rather than one blinking out first. Under reduced motion it simply appears.
 */
export function FloatingPill({ pill }: { pill: FloatingPillContent | null }) {
  const reduced = useReducedMotion();
  const transition = reduced ? { duration: 0 } : PILL_SPRING;
  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-full z-10 mb-3 flex justify-center">
      <AnimatePresence initial={false} mode="popLayout">
        {pill && (
          <motion.div
            key={pill.key}
            data-testid="floating-pill"
            data-floating-pill
            className="pointer-events-auto"
            initial={{ opacity: 0, y: 10, scale: 0.94 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.96 }}
            transition={transition}
          >
            {pill.node}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
