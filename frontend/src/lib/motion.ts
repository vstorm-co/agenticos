import { REDUCED_MOTION_QUERY, resolveReducedMotion } from "@/lib/motion-preference";
import { useMotionStore } from "@/stores/motion-store";

/**
 * The operating system's reduced-motion query, or `null` where there is no
 * `matchMedia` to ask (the server, and a test environment without one).
 */
export function reducedMotionQuery(): MediaQueryList | null {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(REDUCED_MOTION_QUERY)
    : null;
}

/**
 * Whether this reader has asked for less movement, and what to do about it.
 *
 * One place, because the answer was being worked out in several - the
 * dashboard's FLIP, the onboarding spotlight, the theme swap and the streaming
 * text each carried their own copy of the same media query. It is the person's
 * Motion preference (Settings → Profile → Appearance) resolved against the
 * operating system's, read at the moment it is needed rather than subscribed to:
 * nothing here animates for long enough that a preference changed mid-glide
 * would be worth a listener. A component that renders differently subscribes
 * through `useReducedMotion` instead.
 */
export function prefersReducedMotion(): boolean {
  return resolveReducedMotion(
    useMotionStore.getState().motion,
    reducedMotionQuery()?.matches === true,
  );
}

/**
 * The scroll behaviour to ask for: a glide, unless the reader asked for none.
 *
 * `scrollIntoView` takes the preference itself in no browser, so a surface that
 * hardcodes `"smooth"` moves the page under somebody who has said at the
 * operating system that motion makes them ill.
 */
export function glideOrJump(): ScrollBehavior {
  return prefersReducedMotion() ? "auto" : "smooth";
}
