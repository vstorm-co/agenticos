"use client";

import { useSyncExternalStore } from "react";

import { parseShellInfo, type ShellInfo } from "@/lib/desktop/shell";

const noSubscription = () => () => {};

let cached: { source: unknown; info: ShellInfo | null } | undefined;

/** One parsed object per announcement, as `useSyncExternalStore` requires of a snapshot. */
function snapshot(): ShellInfo | null {
  const source = window.__AGENTICOS_SHELL__;
  if (cached !== undefined && cached.source === source) return cached.info;
  cached = { source, info: parseShellInfo(source) };
  return cached.info;
}

/**
 * The desktop app this page is inside, or `null` in a browser.
 *
 * A snapshot that cannot change after the page loads - the shell announces
 * itself before any script runs - read through `useSyncExternalStore` so the
 * server's render (`null`) and the client's first render agree, and the shell
 * arrives on the render after hydration rather than as a mismatch.
 */
export function useShell(): ShellInfo | null {
  return useSyncExternalStore(noSubscription, snapshot, () => null);
}
