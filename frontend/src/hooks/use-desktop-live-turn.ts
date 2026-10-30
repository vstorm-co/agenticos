"use client";
import { useEffect, useId } from "react";
import { useShell } from "./use-shell";
import { isDesktopShell } from "@/lib/desktop/shell";
import { useDesktopLiveStore, type DesktopLiveTurn } from "@/stores/desktop-live-store";
export function useDesktopLiveTurn(
  conversation: string | null,
  state: DesktopLiveTurn["state"] | null,
  canStop: () => boolean,
) {
  const id = useId();
  const shell = useShell();
  const put = useDesktopLiveStore((s) => s.set);
  useEffect(() => {
    if (isDesktopShell(shell))
      put(id, conversation && state ? { conversation, state, canStop: canStop() } : null);
    return () => put(id, null);
  }, [id, shell, conversation, state, canStop, put]);
}
