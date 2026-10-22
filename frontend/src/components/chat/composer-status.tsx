"use client";

import { useTranslations } from "next-intl";

import { RestartTourButton } from "@/components/onboarding/restart-tour-button";
import { cn } from "@/lib/utils";

/**
 * The line under the composer: the page's help and - only when it is bad news -
 * the connection. No "AI can make mistakes" line: nothing requires it where the
 * reader can see they are talking to an agent, and under every message it was
 * one more thing to read past (#2301).
 *
 * A live connection says nothing visible. "LIVE" beside a green dot on every
 * message was a reading everybody had to read past to learn that nothing was
 * wrong; "Offline" is the one state worth the width, because a composer that
 * cannot send otherwise looks the same. It is still read aloud either way.
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

  return (
    // Footnote size: at `text-xs` in a pill it was the loudest line under the box.
    <div
      className={cn(
        "text-muted-foreground/80 flex items-center justify-center gap-1.5 px-1 leading-none",
        compact ? "mt-1 h-4 text-[10px]" : "mt-1 h-5 text-[11px]",
      )}
    >
      <span role="status" className={isConnected ? "sr-only" : "contents"}>
        {isConnected ? (
          tc("live")
        ) : (
          <span className="bg-background text-destructive inline-flex shrink-0 items-center gap-1.5 rounded-sm px-1 py-0.5 font-medium">
            <span aria-hidden className="bg-destructive inline-block h-1.5 w-1.5 rounded-full" />
            {tc("offline")}
          </span>
        )}
      </span>
      {/* Chat is the one surface with no PageHeader, so the "?" that replays a
          page's tips lives here rather than among the controls, where it was the
          one button that did not act on the message being written. */}
      <span className="[&_button]:text-muted-foreground/80 contents [&_button]:size-5 [&_svg]:size-3">
        <RestartTourButton />
      </span>
    </div>
  );
}
