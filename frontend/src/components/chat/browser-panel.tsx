"use client";

import { Play, X } from "lucide-react";
import { useEffect } from "react";
import { useTranslations } from "next-intl";

import { useShell } from "@/hooks/use-shell";
import { isDesktopShell } from "@/lib/desktop/shell";
import { NativeBrowser } from "./native-browser";
import { BrowserPanelFrame } from "./browser-panel-frame";
import { useLiveBrowse } from "@/hooks/use-live-browse";
import {
  browseById,
  isRunning,
  latestBrowserTabs,
  withLivePreview,
  type Browse,
} from "@/lib/browse";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";
import type { PageComment } from "./browser-comment";
import { BrowserTabs } from "./browser-tabs";
import { BrowserWindow } from "./browser-window";

/** One selected browse beside the chat, or full screen when space is limited. */
export function BrowserPanel({
  browses,
  onComment,
  onResume,
}: {
  browses: Browse[];
  onResume?: () => void;
  /** Where a comment on the page goes - the conversation's composer. */
  onComment?: (comment: PageComment) => void;
}) {
  const openCallId = useBrowserPanelStore((state) => state.openCallId);
  // The browse somebody opened, by id - never "the running one". A view that
  // followed whichever browse advanced last would swap page under a reader the
  // moment the other one moved.
  const tabs = latestBrowserTabs(browses);
  const selected = browseById(browses, openCallId);
  // A resumed run gives the same tab a new call id; keep its selected page live.
  const streamed = selected?.tabId
    ? (tabs.find((tab) => tab.tabId === selected.tabId) ?? selected)
    : selected;
  // Mounted only with something to show, so a conversation that is not
  // browsing opens no live view and holds no socket for one.
  return streamed === null ? null : (
    <OpenBrowser
      key={streamed.callId}
      streamed={streamed}
      tabs={tabs}
      onComment={onComment}
      onResume={onResume}
    />
  );
}

/** A stable selected browse; changing layout keeps its socket and native page mounted. */
function OpenBrowser({
  streamed,
  tabs,
  onComment,
  onResume,
}: {
  streamed: Browse;
  tabs: Browse[];
  onResume?: () => void;
  onComment?: (comment: PageComment) => void;
}) {
  const close = useBrowserPanelStore((state) => state.close);
  const open = useBrowserPanelStore((state) => state.open);
  const shell = useShell();
  const t = useTranslations("browse");
  const chat = useTranslations("chat");
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
    <BrowserPanelFrame>
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
