/**
 * Whether this browser has ever used the page-help button.
 *
 * The "?" in every page header is easy to miss, so it breathes until somebody
 * presses it — and then never again, because a hint that never stops is a piece
 * of chrome that moves for the rest of the product's life. One flag, in
 * `localStorage`, because the question is "has this reader noticed the control",
 * which is about a browser rather than an account: it is not onboarding progress
 * (that stays server truth on the user row) and nothing depends on it being
 * right — the worst a lost flag costs is a few more seconds of a soft pulse.
 *
 * Exposed as an external store rather than a plain getter so a component can read
 * it through `useSyncExternalStore`: the value exists only on the client, and that
 * is the hook that lets the server render one answer ("used", so nothing pulses)
 * and the browser correct it after hydration without a `setState` in an effect.
 */
const KEY = "agenticos:page-help-used";

const listeners = new Set<() => void>();

/** True once the reader has opened page help at least once in this browser. */
export function hasUsedPageHelp(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    // Storage refused (private mode). Treat it as used: a hint that cannot
    // remember being dismissed would pulse on every page, forever.
    return true;
  }
}

/** What the server renders — no storage there, and nothing should pulse in HTML. */
export function hasUsedPageHelpOnServer(): boolean {
  return true;
}

/** Record that they have, so the hint stops everywhere it is being read. */
export function markPageHelpUsed(): void {
  try {
    localStorage.setItem(KEY, "1");
  } catch {
    // Nothing to do — the hint keeps pulsing this session and stops next time
    // storage works. It must not break opening the walkthrough.
  }
  for (const listener of listeners) listener();
}

/** Subscribe to the flag being set, for `useSyncExternalStore`. */
export function subscribeToPageHelp(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
