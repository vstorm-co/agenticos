"use client";

import { useSyncExternalStore } from "react";

const noSubscription = () => () => {};
const onTheClient = () => true;
const onTheServer = () => false;

/**
 * Whether this render is past hydration.
 *
 * `false` on the server and during hydration, `true` on every client render after
 * it - for a decision the server cannot make, such as whether the page is inside
 * the desktop app, so the first paint shows nothing rather than the wrong answer.
 */
export function useHydrated(): boolean {
  return useSyncExternalStore(noSubscription, onTheClient, onTheServer);
}
