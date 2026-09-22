"use client";

import { useSyncExternalStore } from "react";

/**
 * Whether this render is the browser's rather than the server's.
 *
 * For a component whose correct output depends on something only the browser
 * knows - a `localStorage` preference, `prefers-color-scheme` - where rendering
 * the real answer on the first pass is a hydration mismatch. The server has no
 * `localStorage`, so it renders the store's default; a `persist` middleware
 * reads the stored value *synchronously*, so the browser's first render already
 * has the real one. React then finds two different trees and rebuilds, which is
 * a console error and a visible flash of the wrong state on every reload.
 *
 * Gating on this makes both first renders agree on the default, and the truth
 * arrives one render later.
 *
 * `useSyncExternalStore` rather than `useState` + `useEffect`: it answers
 * without a state write, so there is no extra commit and nothing to forget in a
 * dependency array. The subscribe callback is a no-op that is never called,
 * because the value cannot change after mount - `false` on the server,
 * `true` everywhere else, for ever.
 *
 * Extracted because it was written out twice - the theme toggle and the account
 * menu's appearance submenu - and the collapsed sidebar would have been the
 * third, having first shipped without it.
 */
export function useMounted(): boolean {
  return useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
}
