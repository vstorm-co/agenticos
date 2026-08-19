"use client";

import { useSyncExternalStore } from "react";
import { AlertTriangle, Info, Megaphone, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { useBrandingNotice } from "@/hooks/use-branding-notice";
import type { NoticeLevel } from "@/lib/branding";
import { cn } from "@/lib/utils";

/**
 * What the deployment's administrator wants everyone using it to read.
 *
 * Dismissible, and keyed on **the message itself** rather than on a flag or on the
 * settings row's timestamp. A flag means the next announcement is invisible to
 * anybody who dismissed the last one; the row's timestamp means renaming the
 * deployment un-dismisses a notice nobody asked to see again. The text is the
 * thing that changed, so the text is the key.
 *
 * `localStorage` rather than a column: this is a preference of one browser about
 * one sentence, and a round trip to store it would be a write on every dismissal
 * of a message that expires by being replaced.
 *
 * The key is `deployment.notice`, matching `cookie.consent` beside it and
 * deliberately not carrying the product's name: an internal key that spells the
 * name reads as one a rename should follow, and renaming a deployment must not
 * un-dismiss a banner for everybody using it.
 *
 * Read through `useSyncExternalStore` rather than in an effect. The store is a
 * browser API the server has no snapshot of, so the server snapshot is "nothing
 * dismissed" and the client's first commit is the real answer - which is exactly
 * what this hook exists for, and what a `setState` in an effect only approximates
 * at the cost of a cascading render.
 */
const DISMISSED_KEY = "deployment.notice";

const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function readDismissed(): string | null {
  return window.localStorage.getItem(DISMISSED_KEY);
}

/** The server has no `localStorage`, so nothing is dismissed there. */
function noneDismissed(): null {
  return null;
}

function dismiss(message: string): void {
  window.localStorage.setItem(DISMISSED_KEY, message);
  for (const listener of listeners) listener();
}

const TONE: Record<NoticeLevel, { wrapper: string; icon: typeof Info }> = {
  info: { wrapper: "border-border bg-muted/60 text-foreground", icon: Info },
  warning: { wrapper: "border-warning/40 bg-warning/10 text-foreground", icon: Megaphone },
  critical: {
    wrapper: "border-destructive/40 bg-destructive/10 text-foreground",
    icon: AlertTriangle,
  },
};

export function AnnouncementBanner({ enabled }: { enabled: boolean }) {
  const t = useTranslations("common");
  const { data } = useBrandingNotice(enabled);
  const message = data?.message ?? null;
  const dismissed = useSyncExternalStore(subscribe, readDismissed, noneDismissed);

  if (!message || dismissed === message) return null;

  const tone = TONE[data?.level ?? "info"];
  const Icon = tone.icon;

  return (
    <div
      role="status"
      className={cn("flex items-start gap-3 rounded-xl border px-4 py-3 text-sm", tone.wrapper)}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <p className="min-w-0 flex-1 break-words">{message}</p>
      <button
        type="button"
        onClick={() => dismiss(message)}
        aria-label={t("dismiss")}
        className="text-foreground/50 hover:text-foreground -mr-1 shrink-0 rounded p-0.5 transition-colors"
      >
        <X className="h-3.5 w-3.5" aria-hidden />
      </button>
    </div>
  );
}
