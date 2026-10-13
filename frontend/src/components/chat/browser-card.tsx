"use client";

import { Expand, PanelRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { isRunning, type Browse } from "@/lib/browse";
import { cn } from "@/lib/utils";
import { useBrowserPanelStore, type BrowserViewMode } from "@/stores/browser-panel-store";
import { ActionLine, AddressBar, LiveBadge, useProgress, Viewport } from "./browser-view";

/**
 * Every browse of the turn, each as its own card, two across where there is room.
 *
 * One card per browse rather than one for "the current one". An agent asked to
 * compare two pages browses both at once, and a single card showing whichever
 * advanced last is a card that swaps page under somebody reading it.
 *
 * Aligned to the message column rather than the container, so a card sits under
 * the sentence that produced it instead of under the avatar beside it.
 */
export function BrowserCards({ browses }: { browses: Browse[] }) {
  if (browses.length === 0) return null;
  return (
    <div
      className={cn(
        "ml-10 grid gap-3 pb-2 sm:ml-[52px]",
        // One browse gets the column, up to a window's width; two sit side by side.
        browses.length > 1 ? "lg:grid-cols-2" : "max-w-2xl",
      )}
    >
      {browses.map((browse) => (
        <BrowserCard key={browse.callId} browse={browse} />
      ))}
    </div>
  );
}

/** One of the two ways to expand a browse, in the window's own toolbar. */
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
        "text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] rounded-md p-1.5 transition-colors",
        active && "text-foreground bg-foreground/[0.06]",
      )}
    >
      <Icon className="size-3.5" aria-hidden />
    </button>
  );
}

/**
 * One browse, drawn as the browser window it is.
 *
 * The way computer-use agents show their screen: a window with its own address
 * bar, the page as the agent sees it, and underneath the one thing it is doing
 * now with the reason it gave. A person glancing at the chat can tell which site
 * the agent is on and whether it is heading the right way without opening
 * anything; the panel is there for the whole trace.
 *
 * A finished browse stays as its card, because *blocked by the page* is an answer
 * somebody should be able to read after the turn is over.
 */
function BrowserCard({ browse }: { browse: Browse }) {
  const t = useTranslations("chat");
  const open = useBrowserPanelStore((state) => state.open);
  const progress = useProgress(browse);
  const running = isRunning(browse);
  const latest = browse.steps.at(-1);

  return (
    <div className="border-border bg-card overflow-hidden rounded-2xl border shadow-sm">
      <div className="flex items-center gap-2 px-3 pt-2.5 pb-2">
        <AddressBar url={browse.url} className="flex-1" />
        <LiveBadge browse={browse} />
        <div className="flex shrink-0 items-center">
          <ExpandButton
            browse={browse}
            mode="panel"
            label={t("browserOpenPanel")}
            icon={PanelRight}
          />
          <ExpandButton browse={browse} mode="full" label={t("browserOpenFull")} icon={Expand} />
        </div>
      </div>

      {/* The page is the primary action: clicking it opens the side panel,
          which is what somebody reaching for a small view wants. */}
      <button
        type="button"
        onClick={() => open(browse.callId, "panel")}
        aria-label={t("browserOpenPanel")}
        className="border-foreground/8 block w-full border-y"
      >
        <Viewport browse={browse} inset />
      </button>

      <div className="flex min-w-0 items-start gap-3 px-3 py-2.5">
        <div className="min-w-0 flex-1">
          {latest ? (
            <ActionLine step={latest} live={running} />
          ) : (
            <p className="text-muted-foreground text-sm">{t("browserStarting")}</p>
          )}
        </div>
        {running && (
          <span className="text-muted-foreground shrink-0 pt-0.5 font-mono text-xs tabular-nums">
            {progress}
          </span>
        )}
      </div>
    </div>
  );
}
