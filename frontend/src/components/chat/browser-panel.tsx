"use client";

import { Play, X } from "lucide-react";
import { useEffect } from "react";
import { useTranslations } from "next-intl";

import { useShell } from "@/hooks/use-shell";
import { isDesktopShell } from "@/lib/desktop/shell";
import { NativeBrowser } from "./native-browser";
import { BrowserPanelFrame } from "./browser-panel-frame";
import { useLiveBrowse } from "@/hooks/use-live-browse";
import { isRunning, latestBrowserTabs, withLivePreview, type Browse } from "@/lib/browse";
import { useBrowserPanelStore, type BrowseSurface } from "@/stores/browser-panel-store";
import {
  browseSurface,
  selectedWorkspaceBrowse,
  workspaceStartReason,
  type WorkspaceStartAccess,
} from "@/lib/workspace-panels";
import { WorkspaceEmpty } from "./workspace-empty";
import type { PageComment } from "./browser-comment";
import { BrowserTabs } from "./browser-tabs";
import { BrowserWindow } from "./browser-window";

const NO_SURFACES: ReadonlyMap<string, BrowseSurface> = new Map();

/** One selected browse beside the chat, or full screen when space is limited. */
export function BrowserPanel({
  browses,
  onComment,
  onResume,
  surfaces = NO_SURFACES,
  access,
  onStart,
  panelId,
}: {
  browses: Browse[];
  onResume?: () => void;
  /** Where a comment on the page goes - the conversation's composer. */
  onComment?: (comment: PageComment) => void;
  surfaces?: ReadonlyMap<string, BrowseSurface>;
  access?: WorkspaceStartAccess;
  onStart?: (surface: BrowseSurface, url?: string) => void;
  panelId?: string;
}) {
  const openCallId = useBrowserPanelStore((state) => state.openCallId);
  const surface = useBrowserPanelStore((state) => state.surface);
  if (surface === null || surface === "files") return null;
  // The browse somebody opened, by id - never "the running one". A view that
  // followed whichever browse advanced last would swap page under a reader the
  // moment the other one moved.
  const candidates = browses.filter(
    (browse) =>
      browseSurface(browse, surfaces) === surface && (openCallId !== null || !browse.nativeId),
  );
  const tabs = surface === "browser" ? latestBrowserTabs(candidates) : [];
  const streamed = selectedWorkspaceBrowse(browses, surfaces, surface, openCallId);
  // Mounted only with something to show, so a conversation that is not
  // browsing opens no live view and holds no socket for one.
  return streamed === null ? (
    <WorkspaceEmpty
      key={surface}
      panelId={panelId}
      surface={surface}
      reason={access ? workspaceStartReason(access, surface) : "unknown"}
      onStart={onStart}
    />
  ) : (
    <OpenBrowser
      key={streamed.callId}
      panelId={panelId}
      streamed={streamed}
      tabs={tabs}
      onComment={onComment}
      onResume={onResume}
      surface={surface}
      onStart={access && workspaceStartReason(access, surface) === null ? onStart : undefined}
    />
  );
}

/** A stable selected browse; changing layout keeps its socket and native page mounted. */
function OpenBrowser({
  streamed,
  tabs,
  onComment,
  onResume,
  surface,
  onStart,
  panelId,
}: {
  streamed: Browse;
  tabs: Browse[];
  onResume?: () => void;
  onComment?: (comment: PageComment) => void;
  surface: BrowseSurface;
  onStart?: (surface: BrowseSurface, url?: string) => void;
  panelId?: string;
}) {
  const close = useBrowserPanelStore((state) => state.close);
  const open = useBrowserPanelStore((state) => state.open);
  const shell = useShell();
  const t = useTranslations("browse");
  const chat = useTranslations("chat");
  const workspace = useTranslations("chat.workspace");
  const running = isRunning(streamed);
  const live = useLiveBrowse(streamed.runId ?? "", streamed.callId, Boolean(streamed.runId));
  // The chat owns completion; the live view supplies its cached final picture.
  const mine = running && live.browse?.callId === streamed.callId;
  const browse = withLivePreview(streamed, live.browse);
  const holding = Boolean(browse.heldBy);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      // While a person holds the browser, Escape is a key for the page.
      const target = event.target;
      if (
        event.defaultPrevented ||
        (target instanceof HTMLElement && target.closest('[role="menu"], [role="dialog"]'))
      )
        return;
      if (event.key === "Escape" && !holding) close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close, holding]);

  return (
    <BrowserPanelFrame id={panelId} label={workspace(surface)} resizeLabel={workspace("resize")}>
      {({ fullscreen, toggleFullscreen }) => {
        const content = (() => {
          if (browse.nativeId && isDesktopShell(shell) && shell.window === "main")
            return (
              <NativeBrowser
                id={browse.nativeId}
                onClose={close}
                fullscreen={fullscreen}
                onToggleFullscreen={toggleFullscreen}
              />
            );
          if (browse.nativeId)
            return (
              <div className="flex h-full flex-col items-center justify-center gap-4 p-6">
                <p>{t("nativeDesktopOnly")}</p>
                <button type="button" onClick={close}>
                  {chat("browserClose")}
                </button>
              </div>
            );
          return (
            <BrowserWindow
              key={streamed.callId}
              waitForFit
              browse={browse}
              surface={surface}
              control={
                mine && live.status === "live"
                  ? { canControl: live.canControl, canRemember: live.canRemember, send: live.send }
                  : null
              }
              maximized={fullscreen}
              onMaximize={toggleFullscreen}
              maximizeLabel={chat(fullscreen ? "browserDock" : "browserMaximize")}
              onClose={close}
              newTabHref={
                streamed.runId ? `/browse/${streamed.runId}/${streamed.callId}` : undefined
              }
              onComment={onComment}
            />
          );
        })();
        return (
          <>
            {!running && (
              <div className="border-border text-muted-foreground flex items-center gap-3 border-b px-3 py-2 text-xs">
                <span title={workspace("lastViewHint")} className="flex-1">
                  {workspace("lastView")}
                </span>
                {surface === "computer" && onStart && (
                  <button
                    type="button"
                    onClick={() => onStart("computer")}
                    className="hover:text-foreground font-medium"
                  >
                    {workspace("startComputer")}
                  </button>
                )}
              </div>
            )}
            {tabs.length > 0 && (
              <BrowserTabs
                tabs={tabs}
                selected={streamed.callId}
                onSelect={(tab) => open(tab.callId)}
              >
                {browse.outcome && browse.resumable && onResume && (
                  <button
                    type="button"
                    onClick={onResume}
                    className="hover:bg-muted flex shrink-0 items-center gap-1.5 rounded-lg px-2 py-2 text-xs"
                  >
                    <Play className="size-3" aria-hidden />
                    {chat("browserResume")}
                  </button>
                )}
                <button
                  type="button"
                  aria-label={chat("browserClose")}
                  title={chat("browserClose")}
                  onClick={close}
                  className="text-muted-foreground hover:bg-muted hover:text-foreground flex size-7 shrink-0 items-center justify-center rounded-md"
                >
                  <X className="size-3.5" aria-hidden />
                </button>
              </BrowserTabs>
            )}
            <div className="min-h-0 flex-1">{content}</div>
          </>
        );
      }}
    </BrowserPanelFrame>
  );
}
