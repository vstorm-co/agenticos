"use client";

import { useSyncExternalStore } from "react";

import { prefersReducedMotion, reducedMotionQuery } from "@/lib/motion";
import { useMotionStore } from "@/stores/motion-store";

function subscribe(onChange: () => void): () => void {
  const unsubscribeStore = useMotionStore.subscribe(onChange);
  const query = reducedMotionQuery();
  query?.addEventListener("change", onChange);
  return () => {
    unsubscribeStore();
    query?.removeEventListener("change", onChange);
  };
}

/**
 * Whether this person wants less movement - their Motion preference resolved
 * against the operating system's, and re-rendering when either changes.
 *
 * The one source of truth for a component: motion's own `useReducedMotion`
 * reads only the operating system, so it would ignore somebody who chose
 * Reduce or Full under Settings → Profile → Appearance.
 *
 * `false` on the server and through hydration, where the stored preference is
 * not yet known; the real answer arrives in the render after, so the first
 * client render agrees with the server's HTML.
 */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, prefersReducedMotion, () => false);
}
