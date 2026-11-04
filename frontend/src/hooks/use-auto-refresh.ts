"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** The intervals a viewer can pick, in minutes; 0 is off. */
export const AUTO_REFRESH_MINUTES = [0, 1, 5, 15, 60] as const;
export type AutoRefreshMinutes = (typeof AUTO_REFRESH_MINUTES)[number];

const MINUTE_MS = 60_000;

function storageKey(artifactId: string): string {
  return `agenticos:artifact-refresh:${artifactId}`;
}

/** The interval this browser picked for a page, or off when storage holds nothing usable. */
function stored(artifactId: string): AutoRefreshMinutes {
  try {
    const value = Number(localStorage.getItem(storageKey(artifactId)));
    return AUTO_REFRESH_MINUTES.find((minutes) => minutes === value) ?? 0;
  } catch {
    // Storage blocked: every page opens with auto-refresh off.
    return 0;
  }
}

/**
 * Refreshes a live page on the interval this viewer picked for it, remembered
 * per page in this browser.
 *
 * - A tick while the tab is hidden refreshes nothing; the tab coming back
 *   refreshes once if at least one tick was missed, so a page left in the
 *   background for an hour costs one read, not sixty.
 * - Nothing ticks while `stopped` - the data was refused, or no source on the
 *   page could be read - since polling a page that cannot load anything only
 *   adds load. The caller decides when it is stopped; a manual refresh that
 *   answers is what lifts it.
 *
 * `refresh` is read at each tick, so the caller may pass a new function every
 * render without restarting the timer.
 */
export function useAutoRefresh(
  artifactId: string,
  refresh: () => void,
  stopped: boolean,
): { minutes: AutoRefreshMinutes; setMinutes: (minutes: AutoRefreshMinutes) => void } {
  const [minutes, setChoice] = useState<AutoRefreshMinutes>(() => stored(artifactId));
  const latest = useRef(refresh);
  useEffect(() => {
    latest.current = refresh;
  });

  useEffect(() => {
    if (minutes === 0 || stopped) return;
    let missed = false;
    const tick = () => {
      if (document.visibilityState === "hidden") missed = true;
      else latest.current();
    };
    const shown = () => {
      if (document.visibilityState !== "visible" || !missed) return;
      missed = false;
      latest.current();
    };
    const timer = window.setInterval(tick, minutes * MINUTE_MS);
    document.addEventListener("visibilitychange", shown);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", shown);
    };
  }, [minutes, stopped]);

  const setMinutes = useCallback(
    (next: AutoRefreshMinutes) => {
      setChoice(next);
      try {
        localStorage.setItem(storageKey(artifactId), String(next));
      } catch {
        // Storage blocked: the choice holds for as long as the page stays open.
      }
    },
    [artifactId],
  );

  return { minutes, setMinutes };
}
