"use client";

import { Expand, Globe, PanelRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { isRunning, type Browse } from "@/lib/browse";
import { cn } from "@/lib/utils";
import { useBrowserPanelStore, type BrowserViewMode } from "@/stores/browser-panel-store";
import { OUTCOME_TONE, useProgress, Viewport } from "./browser-view";

/**
 * Every browse of the turn, each as its own card, two across where there is room.
 *
 * One card per browse rather than one for "the current one". An agent asked to
 * compare two pages browses both at once, and a single card showing whichever
 * advanced last is a card that swaps page under somebody reading it - and hides
 * half of what the turn is doing.
 *
 * Two columns and no more. A third would put each page under 300 pixels wide,
 * which is a thumbnail of a thumbnail; below `lg` there is not even room for the
 * second, and the cards stack.
 *
 * Aligned to the message column rather than the container, so a card sits under
 * the sentence that produced it instead of under the avatar beside it.
 */
export function BrowserCards({ browses }: { browses: Browse[] }) {
  if (browses.length === 0) return null;
  return (
    <div className="ml-10 grid gap-3 pb-2 sm:ml-[52px] lg:grid-cols-2">
      {browses.map((browse) => (
        <BrowserCard key={browse.callId} browse={browse} />
      ))}
    </div>
  );
}

/**
 * One of the two ways to expand a browse, as a button over the page.
 *
 * Revealed on hover, and on focus as well - a control that only exists while a
 * pointer is over it is a control nobody reaching it by keyboard can find. The
 * panel behind it is not decoration either: these sit over a screenshot of an
 * arbitrary web page, and an icon with no backing is invisible against about
 * half of them.
 */
function ExpandButton({
  browse,
  mode,
  label,
  icon: Icon,
}: {
  browse: Browse;
  mode: BrowserViewMode;
  label: string;
  icon: typeof Expand;
}) {
  const open = useBrowserPanelStore((state) => state.open);
  const openCallId = useBrowserPanelStore((state) => state.openCallId);
  const current = useBrowserPanelStore((state) => state.mode);
  const active = openCallId === browse.callId && current === mode;

  return (
    <button
      type="button"
      onClick={() => open(browse.callId, mode)}
      aria-pressed={active}
      aria-label={label}
      title={label}
      className={cn(
        "bg-background text-foreground/70 border-border border",
        "hover:text-foreground hover:bg-accent rounded-lg p-1.5",
        "opacity-0 transition-all group-focus-within:opacity-100 group-hover:opacity-100",
        "focus-visible:opacity-100",
        active && "text-foreground bg-background/90 opacity-100",
      )}
    >
      <Icon className="h-4 w-4" aria-hidden />
    </button>
  );
}

/**
 * What one browse is doing, with the page as the card rather than beside it.
 *
 * The picture is the point: it is the only part that says what the agent is
 * actually looking at, and a thumbnail in a column next to three lines of text
 * gives the smallest element the most room. So the page is the card, full width,
 * and what it is and how far along goes underneath in the space a caption needs.
 *
 * The default way a browse appears, and a window is what somebody asks for. A
 * full panel opening itself over the conversation says watching the browser
 * matters more than reading the answer, which is true for about four seconds and
 * wrong for the rest of the turn. A finished browse stays as its card rather
 * than vanishing, because *blocked by the page* is an answer somebody should be
 * able to read after the turn is over.
 */
function BrowserCard({ browse }: { browse: Browse }) {
  const t = useTranslations("chat");
  const open = useBrowserPanelStore((state) => state.open);
  const progress = useProgress(browse);

  return (
    <div
      className={cn(
        "group border-border bg-card",
        "hover:border-foreground/20 overflow-hidden rounded-2xl border shadow-sm",
        "transition-colors",
      )}
    >
      <div className="relative">
        {/* The page is the primary action: clicking it opens the side panel,
            which is what somebody reaching for a small view wants. */}
        <button
          type="button"
          onClick={() => open(browse.callId, "panel")}
          aria-label={t("browserOpenPanel")}
          className="border-foreground/10 block w-full border-b"
        >
          <Viewport browse={browse} inset />
        </button>

        {/* Over the page, top right, out of the way of most page chrome. Two
            ways in because they answer different questions: the panel watches a
            browse beside the conversation, full screen reads a page. One button
            guessing between them guesses wrong half the time. */}
        <div className="absolute top-2 right-2 flex gap-1">
          <ExpandButton
            browse={browse}
            mode="panel"
            label={t("browserOpenPanel")}
            icon={PanelRight}
          />
          <ExpandButton browse={browse} mode="full" label={t("browserOpenFull")} icon={Expand} />
        </div>
      </div>

      <div className="flex min-w-0 flex-col gap-1 px-3 py-2.5">
        <div className="flex min-w-0 items-center gap-2">
          <Globe className="text-foreground/40 h-4 w-4 shrink-0" aria-hidden />
          <span className="text-foreground truncate text-sm font-medium">
            {browse.title || t("browserHeading")}
          </span>
          {isRunning(browse) && (
            <span
              className="bg-brand/70 h-1.5 w-1.5 shrink-0 animate-pulse rounded-full"
              aria-hidden
            />
          )}
        </div>

        <div className="flex min-w-0 items-baseline gap-3">
          {browse.url && (
            <span
              className="text-foreground/45 min-w-0 flex-1 truncate font-mono text-xs"
              title={browse.url}
            >
              {browse.url}
            </span>
          )}
          {browse.outcome ? (
            <span
              className={cn("shrink-0 text-xs font-medium", OUTCOME_TONE[browse.outcome])}
              data-testid="card-outcome"
            >
              {t(`browserOutcome.${browse.outcome}`)}
            </span>
          ) : (
            <span className="text-foreground/50 shrink-0 font-mono text-xs tabular-nums">
              {progress}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
