"use client";

import { useCallback, useSyncExternalStore } from "react";
import { ArrowUpRight, MonitorDown, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { useConsolePresentation } from "@/components/settings/console-experience-provider";
import { useShell } from "@/hooks/use-shell";
import { useMounted } from "@/hooks/use-mounted";
import { useAuthStore } from "@/stores";
import { cn } from "@/lib/utils";
import styles from "../onboarding/onboarding-reminder.module.css";

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
export function useDesktopInstallPrompt() {
  const { desktopInstallPrompt } = useConsolePresentation();
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

  const mobile =
    mounted &&
    (/Android|iPhone|iPad|iPod/.test(navigator.userAgent) ||
      (navigator.userAgent.includes("Mac") && navigator.maxTouchPoints > 1));
  const dismiss = () => {
    const until = Date.now() + COOLDOWN;
    try {
      localStorage.setItem(key, String(until));
    } catch {
      // Private browsers can dismiss this invitation for their current session.
      sessionDismissals.set(key, until);
    }
    window.dispatchEvent(new Event(CHANGED));
  };
  return {
    eligible:
      desktopInstallPrompt &&
      mounted &&
      shell === null &&
      Boolean(account) &&
      !dismissed &&
      !mobile,
    dismiss,
  };
}

export function DesktopInstallPrompt() {
  const prompt = useDesktopInstallPrompt();
  return prompt.eligible ? <DesktopInstallCard dismiss={prompt.dismiss} /> : null;
}

export function DesktopInstallCard({
  dismiss,
  embedded = false,
}: {
  dismiss: () => void;
  embedded?: boolean;
}) {
  const t = useTranslations("layout.desktopInstall");
  return (
    <aside className={cn(styles.card, embedded && styles.embedded)} aria-label={t("title")}>
      <div className={styles.heading}>
        <span className={styles.desktopArtwork} aria-hidden>
          <MonitorDown className="size-5" />
        </span>
        <h3>{t("title")}</h3>
        <button
          type="button"
          aria-label={t("dismiss")}
          onClick={dismiss}
          className={styles.dismiss}
        >
          <X className="size-3.5" aria-hidden />
        </button>
      </div>
      <p className={styles.hint}>{t("description")}</p>
      <a
        href="https://github.com/vstorm-co/agenticos/releases/latest"
        target="_blank"
        rel="noopener noreferrer"
        className={styles.action}
      >
        {t("download")}
        <ArrowUpRight className="size-3.5" aria-hidden />
      </a>
    </aside>
  );
}
