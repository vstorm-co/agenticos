"use client";

import { useTranslations } from "next-intl";
import { AppWindow } from "lucide-react";
import type { ReactNode } from "react";

import { useDesktopState } from "@/hooks/use-desktop";
import { useHydrated } from "@/hooks/use-hydrated";
import { useShell } from "@/hooks/use-shell";
import type { DesktopState } from "@/lib/desktop/commands";
import { isDesktopShell } from "@/lib/desktop/shell";

const DESKTOP_DOCS = "https://vstorm-co.github.io/agenticos/desktop/";

/**
 * A desktop tab's body: the settings, once the desktop app has said what they
 * are - and in a browser, which has no app to configure, a word on where these
 * settings live instead of an empty card.
 *
 * The tabs are hidden in a browser; this is for the link somebody followed there.
 */
export function DesktopOnly({ children }: { children: (state: DesktopState) => ReactNode }) {
  const t = useTranslations("desktop.settings");
  const shell = useShell();
  const { data, error } = useDesktopState();

  if (!isDesktopShell(shell)) {
    return <OnlyInTheApp title={t("onlyInApp")} hint={t("onlyInAppHint")} />;
  }
  if (error) {
    return (
      <p role="alert" className="text-destructive text-sm">
        {t("unreadable")}
      </p>
    );
  }
  return data ? <>{children(data)}</> : null;
}

/**
 * Where this page is: not known before hydration, then the app or a browser.
 *
 * The shell announces itself only to the client, so deciding on the server's
 * answer would flash the browser screen inside the app.
 */
function useWhere(): "unknown" | "app" | "browser" {
  const shell = useShell();
  const hydrated = useHydrated();
  if (!hydrated) return "unknown";
  return isDesktopShell(shell) ? "app" : "browser";
}

/**
 * A window of the desktop app's own - blobby, quick ask - as a page.
 *
 * In a browser it is one screen saying where it opens, rather than an empty
 * page or controls that cannot reach the app.
 */
export function DesktopPage({ children }: { children: ReactNode }) {
  const where = useWhere();
  if (where === "unknown") return null;
  return where === "app" ? <>{children}</> : <OnlyInTheAppScreen />;
}

/**
 * A settings tab whose every section belongs to the desktop app.
 *
 * In a browser it is one card rather than one per section. Inside the app it
 * gates nothing else: each section reads the app's state, or reports it could
 * not, on its own - so a readiness panel still shows when the state is unreadable.
 */
export function DesktopTab({ children }: { children: ReactNode }) {
  const t = useTranslations("desktop.settings");
  const where = useWhere();
  if (where === "unknown") return null;
  if (where === "app") return <>{children}</>;
  return <OnlyInTheApp title={t("onlyInApp")} hint={t("onlyInAppHint")} />;
}

/** The whole-page form of the browser screen, for a page that is all the app's. */
export function OnlyInTheAppScreen() {
  const t = useTranslations("desktop.onlyInApp");
  return (
    <main className="flex min-h-dvh items-center justify-center p-6">
      <OnlyInTheApp title={t("title")} hint={t("hint")} />
    </main>
  );
}

function OnlyInTheApp({ title, hint }: { title: string; hint: string }) {
  const t = useTranslations("desktop.settings");
  return (
    <div className="border-border bg-card flex flex-col items-start gap-2 rounded-xl border px-5 py-6">
      <AppWindow className="text-muted-foreground size-5" aria-hidden />
      <p className="text-foreground text-sm font-medium">{title}</p>
      <p className="text-muted-foreground text-sm">{hint}</p>
      <a
        href={DESKTOP_DOCS}
        className="text-brand text-sm hover:underline"
        target="_blank"
        rel="noreferrer"
      >
        {t("aboutTheApp")}
      </a>
    </div>
  );
}

/** One labelled setting in a desktop card: what it is, what it means, and its control. */
export function DesktopSetting({
  id,
  label,
  hint,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-6">
      <div className="min-w-0">
        <p id={id} className="text-foreground text-sm font-medium">
          {label}
        </p>
        {hint ? <p className="text-muted-foreground mt-0.5 text-xs">{hint}</p> : null}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}
