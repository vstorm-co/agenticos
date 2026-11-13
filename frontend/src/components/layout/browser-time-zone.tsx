"use client";

import { useSyncExternalStore, type ReactNode } from "react";
import { NextIntlClientProvider, useLocale } from "next-intl";

const subscribe = () => () => {};
const browserZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone;
const serverZone = () => undefined;

/**
 * Dates and times in the reader's own time zone, as Chat and Tables show them.
 *
 * next-intl hands the client the zone the server rendered in, and a container's
 * is UTC. The first client render keeps that zone so hydration matches the
 * server's HTML; the browser's zone takes over straight after. Messages and
 * formats are inherited from the provider above.
 */
export function BrowserTimeZone({ children }: { children: ReactNode }) {
  const locale = useLocale();
  const timeZone = useSyncExternalStore(subscribe, browserZone, serverZone);
  return (
    <NextIntlClientProvider locale={locale} timeZone={timeZone}>
      {children}
    </NextIntlClientProvider>
  );
}
