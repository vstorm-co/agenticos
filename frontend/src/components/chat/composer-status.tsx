"use client";

import { useTranslations } from "next-intl";

import { RestartTourButton } from "@/components/onboarding/restart-tour-button";

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
export function ComposerStatus({ isConnected }: { isConnected: boolean }) {
  const t = useTranslations("chat");
  const tc = useTranslations("common");

  return (
    // Footnote size, the way every chat product draws it: the sentence has to
    // be there, and it is read once. At `text-xs` in a pill it was the loudest
    // line under the box.
    <div className="text-muted-foreground/80 mt-1 flex h-5 items-center justify-center gap-1.5 px-1 text-[11px] leading-none">
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
      <span className="bg-background min-w-0 truncate rounded-sm px-1 py-0.5">
        {t("aiCanMakeMistakes")}
      </span>
      {/* Chat is the one surface with no PageHeader, so the "?" that replays a
          page's tips lives here - beside the disclaimer rather than among the
          controls, where it was the one button that did not act on the message
          being written. */}
      <span className="[&_button]:text-muted-foreground/80 contents [&_button]:size-5 [&_svg]:size-3">
        <RestartTourButton />
      </span>
    </div>
  );
}
