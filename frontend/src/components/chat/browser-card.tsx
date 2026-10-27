"use client";

import { createContext, useContext, useEffect, useRef } from "react";

import { Maximize2, Monitor } from "lucide-react";
import { useTranslations } from "next-intl";

import { useShell } from "@/hooks/use-shell";
import { isDesktopShell } from "@/lib/desktop/shell";
import { useLiveBrowse } from "@/hooks/use-live-browse";
import {
  DESKTOP_TOOLS,
  recordedBrowserPage,
  turnBrowseVisits,
  isRunning,
  latestBrowserTabs,
  withLivePreview,
  type Browse,
} from "@/lib/browse";
import { cn } from "@/lib/utils";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";
import type { ToolCall } from "@/types";
import type { PageComment } from "./browser-comment";
import { BrowserWindow, hostOf } from "./browser-window";
import { BrowserVisit } from "./browser-visit";

/** The browses running in this chat, and where a comment on one of their pages goes. */
const LiveBrowses = createContext<{
  browses: Browse[];
  onComment?: (comment: PageComment) => void;
}>({ browses: [] });

function isDesktop(call: ToolCall): boolean {
  return DESKTOP_TOOLS.has(call.name);
}

/** Hands the chat's live browses to the turns that made them. */
export const LiveBrowsesProvider = LiveBrowses.Provider;

/** Browser transcript links and computer previews associated with this turn. */
export function TurnBrowses({ calls }: { calls: ToolCall[] }) {
  const { browses: live, onComment } = useContext(LiveBrowses);
  const visits = turnBrowseVisits(calls, live);
  if (visits.length === 0) return null;
  return (
    <div
      className={cn(
        "grid w-full min-w-0 gap-2 py-1",
        visits.length > 1 ? "md:grid-cols-2" : "max-w-3xl",
      )}
    >
      {visits.map(({ id, call, browse }) =>
        browse ? (
          browse.navigable || browse.nativeId ? (
            <BrowserLink key={id} browse={browse} />
          ) : (
            <InlineBrowser key={id} browse={browse} onComment={onComment} />
          )
        ) : (
          <RecordedBrowse key={id} call={call} />
        ),
      )}
    </div>
  );
}

/** A browse from an earlier turn: where it went, and the way there. */
function RecordedBrowse({ call }: { call: ToolCall }) {
  const t = useTranslations("chat");
  if (!isDesktop(call)) return <BrowserVisit {...recordedBrowserPage(call)} />;
  return (
    <div className="text-muted-foreground flex items-center gap-2 py-1 text-xs">
      <Monitor className="size-4" aria-hidden />
      {t("computerLineUsed")}
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
    Boolean(streamed.runId) && !expanded,
  );
  // The live view's copy while the browse runs: it knows who holds the browser
  // and whether this person may, which the conversation's stream does not say.
  const mine = running && live.browse?.callId === streamed.callId;
  const browse = withLivePreview(streamed, live.browse);
  return (
    <div className="border-border bg-background aspect-[16/11] w-full min-w-0 overflow-hidden rounded-2xl border shadow-sm">
      {expanded ? (
        <button
          type="button"
          onClick={() => expand(streamed.callId)}
          className="text-muted-foreground hover:text-foreground flex h-full w-full flex-col items-center justify-center gap-2 text-sm"
        >
          <Maximize2 className="size-5" aria-hidden />
          {t("browserShownInPanel", { host: hostOf(browse.url) ?? t("browserHeading") })}
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
          maximizeLabel={t("browserOpenPanel")}
          onMaximize={() => expand(streamed.callId)}
          newTabHref={streamed.runId ? `/browse/${streamed.runId}/${streamed.callId}` : undefined}
          onComment={onComment}
        />
      )}
    </div>
  );
}

/** A compact transcript entry that reopens the browser side panel. */
function BrowserLink({ browse }: { browse: Browse }) {
  const open = useBrowserPanelStore((state) => state.open);
  const page = recordedBrowserPage({ args: { url: browse.url }, result: undefined });
  return <BrowserVisit url={page.url} title={browse.title} onOpen={() => open(browse.callId)} />;
}

/** Open each running browser session once, without overriding a reader's selection or closure. */
export function BrowserPanelAutoOpen({ browses }: { browses: Browse[] }) {
  const newest = latestBrowserTabs(browses).at(-1);
  const opened = useRef(new Set<string>());
  const openCallId = useBrowserPanelStore((state) => state.openCallId);
  const open = useBrowserPanelStore((state) => state.open);
  const shell = useShell();
  const callId = newest?.callId;
  const session = newest?.runId ?? callId;
  const running = newest ? isRunning(newest) : false;
  const supported = !newest?.nativeId || (isDesktopShell(shell) && shell.window === "main");
  useEffect(() => {
    if (!callId || !session || !running || !supported || opened.current.has(session)) return;
    opened.current.add(session);
    if (openCallId === null) open(callId);
  }, [callId, session, running, supported, openCallId, open]);
  return null;
}
