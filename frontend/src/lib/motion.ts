/**
 * Whether this reader has asked for less movement, and what to do about it.
 *
 * One place, because the answer was being worked out in three - the dashboard's
 * FLIP, the onboarding spotlight and the theme swap each carried their own copy
 * of the same media query, and a fourth was about to be added for the run
 * detail. The query is read at the moment it is needed rather than subscribed
 * to: nothing here animates for long enough that a preference changed mid-glide
 * would be worth a listener.
 */
export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
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
