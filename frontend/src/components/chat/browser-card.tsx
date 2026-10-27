"use client";

import { createContext, useContext, useEffect, useState } from "react";

import { ArrowUpRight, Globe, Maximize2, Monitor, Play, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { useShell } from "@/hooks/use-shell";
import { isDesktopShell } from "@/lib/desktop/shell";
import { useLiveBrowse } from "@/hooks/use-live-browse";
import {
  DESKTOP_TOOLS,
  isRunning,
  latestBrowserTabs,
  withLivePreview,
  type Browse,
} from "@/lib/browse";
import { cn } from "@/lib/utils";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";
import type { ToolCall } from "@/types";
import type { PageComment } from "./browser-comment";
import { BrowserTabs } from "./browser-tabs";
import { BrowserWindow, hostOf } from "./browser-window";

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
  if (calls.length === 0) return null;
  const windows = calls.flatMap((call) => {
    const browse = live.find((entry) => entry.callId === call.id);
    return browse ? [browse] : [];
  });
  // A desktop has one line however many runs used it, and none beside a window
  // that is showing it: its calls are only candidates for the window a run opened.
  const shown = calls.some((call) => isDesktop(call) && windows.some((w) => w.callId === call.id));
  const firstDesktop = shown ? undefined : calls.find(isDesktop);
  const recorded = calls.filter(
    (call) =>
      !live.some((entry) => entry.callId === call.id) &&
      (!isDesktop(call) || call === firstDesktop),
  );
  return (
    <div className="flex w-full min-w-0 flex-col gap-2 py-1">
      {windows.length > 0 && (
        // One browse is a window at a reading width rather than the whole column,
        // where it towered over the answer; several share the column's width.
        <div className={cn("grid gap-3", windows.length > 1 ? "md:grid-cols-2" : "max-w-3xl")}>
          {windows.map((browse) =>
            browse.navigable || browse.nativeId ? (
              <BrowserLink key={browse.callId} browse={browse} />
            ) : (
              <InlineBrowser key={browse.callId} browse={browse} onComment={onComment} />
            ),
          )}
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
  // `browse_web` names where it started; `browser_open`, where it opened. A
  // desktop has no address, only the fact that one was used.
  const desktop = isDesktop(call);
  const opened = call.args.start_url ?? call.args.url;
  const start = typeof opened === "string" ? opened : null;
  const host = hostOf(start);
  const Icon = desktop ? Monitor : Globe;
  return (
    <div className="bg-foreground/[0.04] flex w-full min-w-0 items-center gap-3 rounded-2xl px-2.5 py-2">
      <span className="ring-foreground/10 bg-background flex h-10 w-14 shrink-0 items-center justify-center rounded-lg ring-1">
        <Icon className="text-muted-foreground size-4" aria-hidden />
      </span>
      <span className="text-foreground min-w-0 flex-1 truncate text-sm font-medium">
        {desktop
          ? t("computerLineUsed")
          : host
            ? t("browserLineBrowsed", { host })
            : t("browserLineBrowsedWeb")}
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
  docked = false,
}: {
  browse: Browse;
  onComment?: (comment: PageComment) => void;
  docked?: boolean;
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
    <div
      className={cn(
        "border-border bg-background w-full min-w-0 overflow-hidden rounded-2xl border shadow-sm",
        docked ? "h-[min(32dvh,320px)] rounded-none border-0 shadow-none" : "aspect-[16/11]",
      )}
    >
      {browse.nativeId ? (
        <button
          type="button"
          onClick={() => expand(streamed.callId)}
          className="text-muted-foreground hover:text-foreground flex h-full w-full flex-col items-center justify-center gap-2 text-sm"
        >
          <Globe className="size-5" aria-hidden />
          {t("browserOpenNative")}
        </button>
      ) : expanded ? (
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

/** A compact transcript entry; the working page stays above the composer. */
function BrowserLink({ browse }: { browse: Browse }) {
  const open = useBrowserPanelStore((state) => state.open);
  const t = useTranslations("chat");
  return (
    <button
      type="button"
      onClick={() => open(browse.callId)}
      className="text-muted-foreground hover:text-foreground flex min-w-0 items-center gap-2 rounded-lg border px-3 py-2 text-sm"
    >
      <Globe className="size-4 shrink-0" aria-hidden />
      <span className="truncate">{browse.title || hostOf(browse.url) || t("browserHeading")}</span>
      <Maximize2 className="ml-auto size-3.5 shrink-0" aria-hidden />
    </button>
  );
}

/** Stable preview independent of the transcript's narration and scroll position. */
export function BrowserDock({
  browses,
  onComment,
  onResume,
}: {
  browses: Browse[];
  onComment?: (comment: PageComment) => void;
  onResume: () => void;
}) {
  const t = useTranslations("chat");
  const tabs = latestBrowserTabs(browses);
  const latest = tabs.at(-1)?.callId;
  const [selection, setSelection] = useState<{ callId: string; latest: string | undefined } | null>(
    null,
  );
  const [hidden, setHidden] = useState<string | null>(null);
  const openCallId = useBrowserPanelStore((state) => state.openCallId);
  const open = useBrowserPanelStore((state) => state.open);
  const shell = useShell();
  const newest = tabs.at(-1);
  useEffect(() => {
    if (newest?.nativeId && isRunning(newest) && isDesktopShell(shell) && shell.window === "main")
      open(newest.callId);
  }, [newest?.callId, newest?.nativeId, newest?.outcome, shell, open]);
  const selectTab = (tab: Browse) => setSelection({ callId: tab.callId, latest });
  const active =
    tabs.find(
      (tab) =>
        tab.callId === (selection && selection.latest === latest ? selection.callId : latest),
    ) ?? tabs.at(-1);
  if (!active || hidden === latest || browses.some((browse) => browse.callId === openCallId))
    return null;
  return (
    <div className="pointer-events-auto mx-auto w-full max-w-5xl px-2 pb-2 sm:px-4">
      <div className="bg-background overflow-hidden rounded-xl border shadow-sm">
        <BrowserTabs tabs={tabs} selected={active.callId} onSelect={selectTab}>
          {active.outcome && active.resumable && !active.nativeId && (
            <button
              type="button"
              onClick={onResume}
              className="text-muted-foreground hover:text-foreground hover:bg-muted flex shrink-0 items-center gap-1.5 rounded-lg px-2 py-2 text-xs"
            >
              <Play className="size-3" aria-hidden />
              {t("browserResume")}
            </button>
          )}
          <button
            type="button"
            aria-label={t("browserClose")}
            onClick={() => setHidden(latest ?? null)}
            className="hover:bg-muted rounded-lg p-2"
          >
            <X className="size-3.5" aria-hidden />
          </button>
        </BrowserTabs>
        <div role="tabpanel" aria-label={active.title || t("browserHeading")}>
          <InlineBrowser key={active.callId} browse={active} onComment={onComment} docked />
        </div>
      </div>
    </div>
  );
}
