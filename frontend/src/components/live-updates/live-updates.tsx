"use client";

import { useLiveUpdates } from "@/hooks/use-live-updates";

/** Holds the console's live-update socket for as long as the dashboard is open. */
export function LiveUpdates() {
  useLiveUpdates();
  return null;
}
