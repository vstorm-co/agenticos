"use client";

import { useCallback, useSyncExternalStore } from "react";
import { MonitorDown, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { useShell } from "@/hooks/use-shell";
import { useMounted } from "@/hooks/use-mounted";
import { useAuthStore } from "@/stores";

const COOLDOWN = 14 * 24 * 60 * 60 * 1000;
const CHANGED = "desktop-install-dismissed";
const sessionDismissals = new Map<string, number>();

function dismissedUntil(key: string): number {
  const session = sessionDismissals.get(key);
  if (session !== undefined) return session;
  try {
    const value = Number(localStorage.getItem(key));
    return Number.isFinite(value) && value > 0 ? value : 0;
  } catch {
    return 0;
  }
}

/** A quiet native-app invitation, separate from the phone's PWA install prompt. */
export function DesktopInstallPrompt() {
  const t = useTranslations("layout.desktopInstall");
  const shell = useShell();
  const mounted = useMounted();
  const account = useAuthStore((state) => state.user?.id);
  const key = `desktop-install:${account ?? "anonymous"}`;
  const subscribe = useCallback(
    (notify: () => void) => {
      let timer: number | undefined;
      const refresh = () => {
        window.clearTimeout(timer);
        const delay = dismissedUntil(key) - Date.now();
        if (delay > 0) timer = window.setTimeout(refresh, Math.min(delay + 1, COOLDOWN + 1));
        notify();
      };
      window.addEventListener("storage", refresh);
      window.addEventListener(CHANGED, refresh);
      refresh();
      return () => {
        window.removeEventListener("storage", refresh);
        window.removeEventListener(CHANGED, refresh);
        window.clearTimeout(timer);
      };
    },
    [key],
  );
  const snapshot = useCallback(() => dismissedUntil(key) > Date.now(), [key]);
  const dismissed = useSyncExternalStore(subscribe, snapshot, () => true);

  if (!mounted || shell !== null || !account || dismissed) return null;
  const mobile =
    /Android|iPhone|iPad|iPod/.test(navigator.userAgent) ||
    (navigator.userAgent.includes("Mac") && navigator.maxTouchPoints > 1);
  if (mobile) return null;

  return (
    <aside
      className="border-border mx-3 mb-2 hidden shrink-0 items-center gap-1 rounded-lg border p-1 md:flex"
      aria-label={t("title")}
    >
      <a
        href="https://github.com/vstorm-co/agenticos/releases/latest"
        target="_blank"
        rel="noopener noreferrer"
        title={t("description")}
        className="hover:bg-accent focus-visible:outline-foreground flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-2 text-xs font-medium focus-visible:outline-2"
      >
        <MonitorDown className="size-4 shrink-0" aria-hidden />
        <span className="truncate">{t("download")}</span>
      </a>
      <button
        type="button"
        aria-label={t("dismiss")}
        onClick={() => {
          const until = Date.now() + COOLDOWN;
          try {
            localStorage.setItem(key, String(until));
          } catch {
            // Private browsers can dismiss this invitation for their current session.
            sessionDismissals.set(key, until);
          }
          window.dispatchEvent(new Event(CHANGED));
        }}
        className="text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-foreground shrink-0 rounded-md p-2 focus-visible:outline-2"
      >
        <X className="size-3.5" aria-hidden />
      </button>
    </aside>
  );
}
