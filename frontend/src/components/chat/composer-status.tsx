"use client";

import { useTranslations } from "next-intl";

/**
 * The connection, read aloud and never drawn.
 *
 * A live connection says nothing visible, and a lost one is said by the box
 * itself - its placeholder reads "Reconnecting…" - where a person looks when
 * they cannot send. A red "Offline" line under the composer said the same thing
 * a second time, in a place nobody was looking (#2301). Nothing else lives here:
 * no "AI can make mistakes" line, and the page's tips are in the chat's settings.
 */
export function ComposerStatus({ isConnected }: { isConnected: boolean }) {
  const tc = useTranslations("common");
  return (
    <span role="status" className="sr-only">
      {isConnected ? tc("live") : tc("offline")}
    </span>
  );
}
