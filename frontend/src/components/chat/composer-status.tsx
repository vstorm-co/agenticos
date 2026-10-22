"use client";

import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

/**
 * The connection, under the composer - and only when it is bad news.
 *
 * A live connection says nothing visible. "LIVE" beside a green dot on every
 * message was a reading everybody had to read past to learn that nothing was
 * wrong; "Offline" is the one state worth the width, because a composer that
 * cannot send otherwise looks the same. It is still read aloud either way.
 *
 * Nothing else lives here (#2301): no "AI can make mistakes" line - nothing
 * requires it where the reader can see they are talking to an agent - and the
 * page's tips moved into the chat's settings, beside the other controls.
 *
 * Opaque, like every other surface: text floating over a transcript collides
 * with whatever scrolls past, and a translucent chip takes its colour from
 * whatever line happens to be under it.
 */
export function ComposerStatus({
  isConnected,
  compact = false,
}: {
  isConnected: boolean;
  /** The narrow chat beside a page: the footnote at its smallest. */
  compact?: boolean;
}) {
  const tc = useTranslations("common");

  if (isConnected) {
    return (
      <span role="status" className="sr-only">
        {tc("live")}
      </span>
    );
  }
  return (
    <div
      className={cn(
        "flex items-center justify-center px-1 leading-none",
        compact ? "mt-1 h-4 text-[10px]" : "mt-1 h-5 text-[11px]",
      )}
    >
      <span
        role="status"
        className="bg-background text-destructive inline-flex shrink-0 items-center gap-1.5 rounded-sm px-1 py-0.5 font-medium"
      >
        <span aria-hidden className="bg-destructive inline-block h-1.5 w-1.5 rounded-full" />
        {tc("offline")}
      </span>
    </div>
  );
}
