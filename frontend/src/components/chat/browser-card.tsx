"use client";

import { ArrowUpRight, Globe, Maximize2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { createContext, useContext } from "react";

import { useLiveBrowse } from "@/hooks/use-live-browse";
import { isRunning, type Browse } from "@/lib/browse";
import { cn } from "@/lib/utils";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";
import type { ToolCall } from "@/types";
import type { PageComment } from "./browser-comment";
import { BrowserWindow, hostOf } from "./browser-window";

/** The browses running in this chat, and where a comment on one of their pages goes. */
const LiveBrowses = createContext<{
  browses: Browse[];
  onComment?: (comment: PageComment) => void;
}>({ browses: [] });

/** Hands the chat's live browses to the turns that made them. */
export const LiveBrowsesProvider = LiveBrowses.Provider;

/**
 * A turn's browses, drawn where the turn made them.
 *
 * Each browse this chat's socket carries is a browser of its own under the
 * message - the page live, at the width of the conversation, with the way to
 * take over - rather than a line that opened a column beside the chat. Several
 * at once sit side by side, two to a row where there is room, so a turn that
 * browses three sites shows three windows rather than one that swaps. A browse
 * from an earlier visit is a record: where it went, and the way there.
 */
export function TurnBrowses({ calls }: { calls: ToolCall[] }) {
  const { browses: live, onComment } = useContext(LiveBrowses);
  if (calls.length === 0) return null;
  const windows = calls.flatMap((call) => {
    const browse = live.find((entry) => entry.callId === call.id);
    return browse ? [browse] : [];
  });
  const recorded = calls.filter((call) => !live.some((entry) => entry.callId === call.id));
  return (
    <div className="flex w-full min-w-0 flex-col gap-2 py-1">
      {windows.length > 0 && (
        // One browse is a window at a reading width rather than the whole column,
        // where it towered over the answer; several share the column's width.
        <div className={cn("grid gap-3", windows.length > 1 ? "md:grid-cols-2" : "max-w-3xl")}>
          {windows.map((browse) => (
            <InlineBrowser key={browse.callId} browse={browse} onComment={onComment} />
          ))}
        </div>
      )}
      {recorded.map((call) => (
        <RecordedBrowse key={call.id} call={call} />
      ))}
    </div>
  );
}

/** A browse from an earlier turn: where it went, and the way there. */
function RecordedBrowse({ call }: { call: ToolCall }) {
  const t = useTranslations("chat");
  const start = typeof call.args.start_url === "string" ? call.args.start_url : null;
  const host = hostOf(start);
  return (
    <div className="bg-foreground/[0.04] flex w-full min-w-0 items-center gap-3 rounded-2xl px-2.5 py-2">
      <span className="ring-foreground/10 bg-background flex h-10 w-14 shrink-0 items-center justify-center rounded-lg ring-1">
        <Globe className="text-muted-foreground size-4" aria-hidden />
      </span>
      <span className="text-foreground min-w-0 flex-1 truncate text-sm font-medium">
        {host ? t("browserLineBrowsed", { host }) : t("browserLineBrowsedWeb")}
      </span>
      {start && host && (
        <a
          href={start}
          target="_blank"
          rel="noopener noreferrer"
          className="text-muted-foreground hover:text-foreground inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium"
        >
          {t("browserVisitSite")}
          <ArrowUpRight className="size-3.5" aria-hidden />
        </a>
      )}
    </div>
  );
}

/**
 * One browse as a browser under the message: a fixed-ratio window that grows and
 * shrinks with the conversation, the page laid out at its size.
 *
 * The live socket is this window's while it shows the browse, and is let go while
 * the same browse is open full screen - one view of a tab holds one socket.
 */
function InlineBrowser({
  browse: streamed,
  onComment,
}: {
  browse: Browse;
  onComment?: (comment: PageComment) => void;
}) {
  const t = useTranslations("chat");
  const expand = useBrowserPanelStore((state) => state.open);
  const expanded = useBrowserPanelStore((state) => state.openCallId === streamed.callId);
  const running = isRunning(streamed);
  const live = useLiveBrowse(
    streamed.runId ?? "",
    streamed.callId,
    running && Boolean(streamed.runId) && !expanded,
  );
  // The live view's copy while the browse runs: it knows who holds the browser
  // and whether this person may, which the conversation's stream does not say.
  const mine = running && live.browse?.callId === streamed.callId;
  const browse = mine && live.browse ? live.browse : streamed;
  return (
    <div className="border-border bg-background aspect-[16/11] w-full min-w-0 overflow-hidden rounded-2xl border shadow-sm">
      {expanded ? (
        <button
          type="button"
          onClick={() => expand(streamed.callId)}
          className="text-muted-foreground hover:text-foreground flex h-full w-full flex-col items-center justify-center gap-2 text-sm"
        >
          <Maximize2 className="size-5" aria-hidden />
          {t("browserShownFullScreen", { host: hostOf(browse.url) ?? t("browserHeading") })}
        </button>
      ) : (
        <BrowserWindow
          waitForFit
          browse={browse}
          control={
            mine && live.status === "live"
              ? { canControl: live.canControl, canRemember: live.canRemember, send: live.send }
              : null
          }
          onMaximize={() => expand(streamed.callId)}
          newTabHref={streamed.runId ? `/browse/${streamed.runId}/${streamed.callId}` : undefined}
          onComment={onComment}
        />
      )}
    </div>
  );
}
