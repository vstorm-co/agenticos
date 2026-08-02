import { useState } from "react";

/**
 * True on the one render where `key` differs from the render before it.
 *
 * For the case React calls "adjusting state when a prop changes": a dialog that
 * clears its draft when it closes, a form that re-seeds when the row underneath
 * it moves. The obvious way to write that is an effect that calls `setState`,
 * and it works — but it renders once with the stale value, commits it, and
 * renders again. The user can see the first one, and the React Compiler cannot
 * optimise a component that does it.
 *
 * Writing the state during render instead means React discards the in-progress
 * output and re-runs the component before committing anything, so the stale
 * value never reaches the screen.
 *
 * ```tsx
 * const [draft, setDraft] = useState(config);
 * if (useChanged(open)) {
 *   if (open) setDraft(config);
 * }
 * ```
 *
 * Compared with `Object.is`, so it is reference equality for objects. Watching
 * several values at once wants a string: `useChanged(`${user.id}|${user.email}`)`.
 * That is deliberate — a shallow-compared object would hide which field moved,
 * and the point of this hook is that the caller says.
 */
export function useChanged<T>(key: T): boolean {
  const [seen, setSeen] = useState(key);
  if (!Object.is(key, seen)) {
    setSeen(key);
    return true;
  }
  return false;
}
