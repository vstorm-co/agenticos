"use client";

import { useEffect } from "react";

import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { isDesktopShell, isMobileShell, readShellInfo } from "@/lib/desktop/shell";
import { sendPresence } from "@/lib/diagnostics";
import { useAuthStore } from "@/stores";

const INTERVAL = 5 * 60 * 1000;

/** Foreground interaction only; never reads the route, text, clipboard or files. */
export function DiagnosticsPresence() {
  const userId = useAuthStore((state) => state.user?.id);
  const authenticated = useAuthStore((state) => state.isAuthenticated);
  const { diagnosticsUrl } = usePublicConfig();
  useEffect(() => {
    if (!userId || !authenticated || !diagnosticsUrl) return;
    const shell = readShellInfo();
    const surface = isDesktopShell(shell) ? "desktop" : isMobileShell(shell) ? "mobile" : "web";
    let lastInteraction = 0,
      lastAttempt: number | null = null;
    let pending = false;
    let controller = new AbortController();
    const report = async () => {
      const now = Date.now();
      if (
        pending ||
        controller.signal.aborted ||
        document.visibilityState !== "visible" ||
        !document.hasFocus() ||
        now - lastInteraction >= INTERVAL ||
        (lastAttempt !== null && now - lastAttempt < INTERVAL)
      )
        return;
      lastAttempt = now;
      pending = true;
      try {
        await sendPresence(surface, diagnosticsUrl, controller.signal);
      } catch {
        // Best effort: no toast, payload logging or immediate retry loop.
        // The admin status reports installation transport failures separately.
      } finally {
        pending = false;
      }
    };
    const interact = () => {
      lastInteraction = Date.now();
      void report();
    };
    const visibility = () => {
      // Opening a background tab does not establish activity. Only input does.
      if (document.visibilityState !== "visible" || !document.hasFocus()) {
        controller.abort();
        return;
      }
      if (controller.signal.aborted) controller = new AbortController();
      void report();
    };
    document.addEventListener("pointerdown", interact, { passive: true });
    document.addEventListener("keydown", interact);
    document.addEventListener("wheel", interact, { passive: true });
    document.addEventListener("visibilitychange", visibility);
    window.addEventListener("focus", visibility);
    window.addEventListener("blur", visibility);
    const interval = setInterval(() => {
      void report();
    }, 30_000);
    return () => {
      controller.abort();
      clearInterval(interval);
      document.removeEventListener("pointerdown", interact);
      document.removeEventListener("keydown", interact);
      document.removeEventListener("wheel", interact);
      document.removeEventListener("visibilitychange", visibility);
      window.removeEventListener("focus", visibility);
      window.removeEventListener("blur", visibility);
    };
  }, [userId, authenticated, diagnosticsUrl]);
  return null;
}
