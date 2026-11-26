"use client";

import { useSyncExternalStore } from "react";

const MINUTE_MS = 60_000;

function subscribe(onChange: () => void) {
  let timer: number;
  const tick = () => {
    onChange();
    timer = window.setTimeout(tick, MINUTE_MS - (Date.now() % MINUTE_MS));
  };
  const wake = () => {
    window.clearTimeout(timer);
    tick();
  };
  timer = window.setTimeout(tick, MINUTE_MS - (Date.now() % MINUTE_MS));
  document.addEventListener("visibilitychange", wake);
  return () => {
    window.clearTimeout(timer);
    document.removeEventListener("visibilitychange", wake);
  };
}

const localMinute = () => Math.floor(Date.now() / MINUTE_MS) * MINUTE_MS;
const serverMinute = () => null;

/** Render local time after hydration and refresh at the next minute or tab wake. */
export function useLocalClock(): Date | null {
  const minute = useSyncExternalStore(subscribe, localMinute, serverMinute);
  return minute === null ? null : new Date(minute);
}
