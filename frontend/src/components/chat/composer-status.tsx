"use client";

import { useTranslations } from "next-intl";

import { RestartTourButton } from "@/components/onboarding/restart-tour-button";
import { cn } from "@/lib/utils";

/**
 * The line under the composer: the disclaimer, the page's help, and - only when
 * it is bad news - the connection.
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
  const t = useTranslations("chat");
  const tc = useTranslations("common");

  return (
    // Footnote size, the way every chat product draws it: the sentence has to
    // be there, and it is read once. At `text-xs` in a pill it was the loudest
    // line under the box.
    <div
      className={cn(
        "text-muted-foreground/80 flex items-center justify-center gap-1.5 px-1 leading-none",
        compact ? "mt-1 h-4 text-[10px]" : "mt-1 h-5 text-[11px]",
        // A phone's chat ends at the composer, as a messenger's does: the line
        // under it is there only to say the connection is gone.
        isConnected && "max-md:hidden",
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
      <span className="bg-background min-w-0 truncate rounded-sm px-1 py-0.5 max-md:hidden">
        {t("aiCanMakeMistakes")}
      </span>
      {/* Chat is the one surface with no PageHeader, so the "?" that replays a
          page's tips lives here - beside the disclaimer rather than among the
          controls, where it was the one button that did not act on the message
          being written. */}
      <span className="[&_button]:text-muted-foreground/80 contents max-md:hidden [&_button]:size-5 [&_svg]:size-3">
        <RestartTourButton />
      </span>
    </div>
  );
}
