"use client";

import { useState, useSyncExternalStore } from "react";
import { AlertTriangle, Info, Megaphone, X } from "lucide-react";
import { useTranslations } from "next-intl";

import type { NoticeLevel, NoticeResponse } from "@/lib/branding";
import styles from "./deployment-notice.module.css";

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

/**
 * What this browser has dismissed, or nothing where it will not say.
 *
 * `localStorage` is not always readable: a browser with site data blocked, a
 * privacy mode, an embedded webview - each throws `SecurityError` on the *getter*.
 * Thrown from here it would be thrown during render, inside
 * `useSyncExternalStore`, and take the whole dashboard down for every signed-in
 * user rather than merely failing to remember a dismissal. Unreadable therefore
 * means "nothing dismissed", which shows the announcement one more time than
 * necessary and is the harmless direction.
 */
function readDismissed(): string | null {
  try {
    return window.localStorage.getItem(DISMISSED_KEY);
  } catch {
    return null;
  }
}

/** The server has no `localStorage`, so nothing is dismissed there. */
function noneDismissed(): null {
  return null;
}

/**
 * Remember the dismissal where the browser allows, and say so either way.
 *
 * The write throws for the same reasons the read does. Answering `false` is what
 * lets the caller keep the banner closed anyway: unstorable is not unimportant, so
 * it goes away now and comes back on the next load rather than refusing to close.
 */
function remember(message: string): boolean {
  try {
    window.localStorage.setItem(DISMISSED_KEY, message);
  } catch {
    return false;
  }
  for (const listener of listeners) listener();
  return true;
}

const ICON: Record<NoticeLevel, typeof Info> = {
  info: Info,
  warning: Megaphone,
  critical: AlertTriangle,
};

/**
 * `notice` rather than a poll of its own: `DeploymentGate` above already asks, and
 * it has to - the maintenance verdict decides whether this banner is even mounted,
 * so a second query for the same row would be a second answer and a second
 * interval. `undefined` while the first answer is in flight, which draws nothing.
 */
export function AnnouncementBanner({ notice }: { notice: NoticeResponse | undefined }) {
  const t = useTranslations("common");
  const noticeText = useTranslations("pages.maintenance");
  const message = notice?.message ?? null;
  const dismissed = useSyncExternalStore(subscribe, readDismissed, noneDismissed);
  // The dismissal a browser refusing storage cannot be told to remember. Held here
  // rather than in a module variable so it lasts exactly as long as it is true of:
  // this mounted banner, in a session where nothing can be written down.
  const [unstorable, setUnstorable] = useState<string | null>(null);

  if (!message || dismissed === message || unstorable === message) return null;

  const level = notice?.level ?? "info";
  const Mark = ICON[level];

  return (
    <div role="status" className={styles.notice} data-level={level}>
      <span className={styles.mark} aria-hidden>
        <Mark className="size-4" />
      </span>
      <div className={styles.content}>
        <p className={styles.label}>{noticeText("announcementTitle")}</p>
        <p className={styles.message}>{message}</p>
      </div>
      <button
        type="button"
        onClick={() => {
          if (!remember(message)) setUnstorable(message);
        }}
        aria-label={t("dismiss")}
        className={styles.dismiss}
      >
        <X className="h-3.5 w-3.5" aria-hidden />
      </button>
    </div>
  );
}
