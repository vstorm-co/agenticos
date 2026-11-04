"use client";

import { useEffect, useState } from "react";
import { Download, Share, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useShell } from "@/hooks/use-shell";

const DISMISSED = "install-prompt-dismissed";

/** Chromium's install event, which no TypeScript library describes yet. */
interface InstallEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

function dismissedBefore(): boolean {
  try {
    return window.localStorage.getItem(DISMISSED) === "1";
  } catch {
    return false;
  }
}

function remember(): void {
  try {
    window.localStorage.setItem(DISMISSED, "1");
  } catch {
    // Private mode: the strip comes back next visit, which is all it costs.
  }
}

/** Safari on an iPhone or iPad, which installs only from its Share sheet. */
function isIosSafari(): boolean {
  const agent = window.navigator.userAgent;
  const ios = /iPhone|iPad|iPod/.test(agent) || (agent.includes("Mac") && "ontouchend" in document);
  return ios && !/CriOS|FxiOS|EdgiOS/.test(agent);
}

function installed(): boolean {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    (window.navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

/**
 * Offers to install the console as an app (#2097, item 12).
 *
 * Where the browser can install it, its own prompt is a button away; on an
 * iPhone, which only installs from Safari's Share sheet, the strip says where
 * to tap. Never inside the desktop or phone app, never once installed, and
 * gone for good once dismissed in this browser.
 */
export function InstallPrompt() {
  const t = useTranslations("layout.install");
  const shell = useShell();
  const [event, setEvent] = useState<InstallEvent | null>(null);
  const [ios, setIos] = useState(false);
  const [hidden, setHidden] = useState(true);

  useEffect(() => {
    if (shell !== null || installed() || dismissedBefore()) return;
    const offered = (raw: Event) => {
      raw.preventDefault();
      setEvent(raw as InstallEvent);
      setHidden(false);
    };
    window.addEventListener("beforeinstallprompt", offered);
    const iphone = isIosSafari();
    // A browser event, not a render, decides this: set once the page is in one.
    const timer = window.setTimeout(() => {
      setIos(iphone);
      if (iphone) setHidden(false);
    }, 0);
    return () => {
      window.removeEventListener("beforeinstallprompt", offered);
      window.clearTimeout(timer);
    };
  }, [shell]);

  if (hidden || (event === null && !ios)) return null;

  const close = () => {
    remember();
    setHidden(true);
  };

  return (
    <div
      role="status"
      className="bg-muted text-foreground flex items-center gap-3 border-b px-4 py-2 text-sm"
    >
      {event !== null ? (
        <Download className="h-4 w-4 shrink-0" aria-hidden />
      ) : (
        <Share className="h-4 w-4 shrink-0" aria-hidden />
      )}
      <p className="min-w-0 flex-1">{event !== null ? t("offer") : t("iosHint")}</p>
      {event !== null && (
        <Button
          size="sm"
          onClick={async () => {
            await event.prompt();
            const choice = await event.userChoice;
            if (choice.outcome === "accepted") setHidden(true);
            setEvent(null);
          }}
        >
          {t("install")}
        </Button>
      )}
      <button
        type="button"
        onClick={close}
        aria-label={t("dismiss")}
        className="text-muted-foreground hover:text-foreground rounded p-1"
      >
        <X className="h-4 w-4" aria-hidden />
      </button>
    </div>
  );
}
