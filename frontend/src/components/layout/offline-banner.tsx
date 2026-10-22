"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { CloudOff, Send } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { useMounted } from "@/hooks/use-mounted";
import { useOnline } from "@/hooks/use-online";
import { ROUTES } from "@/lib/constants";
import { keepConsoleCode, offlineAvailable, refreshOutboxCounts } from "@/lib/offline/device-cache";
import { useAuthStore, useConversationStore, useOfflineStore } from "@/stores";

/**
 * The strip that says the console is working from its copy on the device, and
 * what waits to be sent (#2097).
 *
 * Offline it says so, and since when the screen is a copy - and the same when
 * the device has a network and the server does not answer. The outbox is
 * named whether or not there is a network: a message sends from its own
 * conversation, so one written in another thread - or before the app was
 * closed - waits for that conversation to be opened, and this is where the
 * person learns it is waiting and goes there.
 *
 * Only in the apps, which are the only consoles that keep a copy.
 */
export function OfflineBanner() {
  const t = useTranslations("layout.offline");
  const locale = useLocale();
  const mounted = useMounted();
  const online = useOnline();
  const savedAt = useOfflineStore((state) => state.savedAt);
  const outbox = useOfflineStore((state) => state.outbox);
  const userId = useAuthStore((state) => state.user?.id);
  const openId = useConversationStore((state) => state.currentConversationId);
  const available = mounted && offlineAvailable();

  useEffect(() => {
    if (available) void keepConsoleCode();
  }, [available]);

  useEffect(() => {
    if (available && userId) void refreshOutboxCounts();
  }, [available, userId]);

  // The network coming back, not the banner mounting online: a copy served
  // because the server could not be reached says so until the server answers.
  const wasOnline = useRef(online);
  useEffect(() => {
    if (online && !wasOnline.current) useOfflineStore.getState().backOnline();
    wasOnline.current = online;
  }, [online]);

  if (!available) return null;
  const elsewhere = outbox.filter((entry) => entry.conversationId !== openId);
  const waiting = elsewhere.reduce((sum, entry) => sum + entry.count, 0);
  const savedTime =
    savedAt &&
    new Intl.DateTimeFormat(locale, { dateStyle: "short", timeStyle: "short" }).format(savedAt);
  const notice = !online
    ? savedTime
      ? t("savedCopy", { time: savedTime })
      : t("noNetwork")
    : savedTime
      ? t("unreachable", { time: savedTime })
      : null;
  if (notice === null && waiting === 0) return null;

  const first = elsewhere[0];
  const href = first?.conversationId ? `${ROUTES.CHAT}?id=${first.conversationId}` : ROUTES.CHAT;

  return (
    <div
      role="status"
      className="bg-muted text-foreground flex flex-wrap items-center gap-x-3 gap-y-1 border-b px-4 py-2 text-sm"
    >
      {notice !== null && (
        <>
          <CloudOff className="h-4 w-4 shrink-0" aria-hidden />
          <p className="min-w-0 flex-1">{notice}</p>
        </>
      )}
      {waiting > 0 && (
        <Link
          href={href}
          className="text-foreground inline-flex shrink-0 items-center gap-1.5 text-xs font-medium hover:underline max-sm:ml-auto"
        >
          <Send className="h-3.5 w-3.5" aria-hidden />
          {t("outboxWaiting", { count: waiting })}
        </Link>
      )}
    </div>
  );
}
