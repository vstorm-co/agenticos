"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Which node the map has focused, and the two ways out of it.
 *
 * Focus is the whole of the map's interactivity: a node picked out, its edge lit,
 * the rest dimmed, and a panel saying what it holds. Escape clears it because a
 * detail panel with no way back but the mouse is a trap for anyone on a keyboard;
 * clicking the empty canvas clears it because that is where a person aims to mean
 * "never mind". Toggling the same node off is the third - a second press on what
 * is already focused is a request to stop looking at it.
 */
export function useFocusedNode() {
  const [focused, setFocused] = useState<string | null>(null);

  const clear = useCallback(() => setFocused(null), []);
  const focus = useCallback(
    (key: string) => setFocused((current) => (current === key ? null : key)),
    [],
  );

  useEffect(() => {
    if (focused === null) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFocused(null);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [focused]);

  return { focused, focus, clear };
}
