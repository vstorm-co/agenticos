"use client";

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
}: {
  browses: Browse[];
  /** Where a comment on the page goes - the conversation's composer. */
  onComment?: (comment: PageComment) => void;
}) {
  const openCallId = useBrowserPanelStore((state) => state.openCallId);
  // The browse somebody opened, by id - never "the running one". A view that
  // followed whichever browse advanced last would swap page under a reader the
  // moment the other one moved.
  const streamed = browseById(browses, openCallId);
  // Mounted only with something to show, so a conversation that is not
  // browsing opens no live view and holds no socket for one.
  return streamed === null ? null : (
    <OpenBrowser
      key={streamed.callId}
      streamed={streamed}
      tabs={latestBrowserTabs(browses)}
      onComment={onComment}
    />
  );
}

/** A stable selected browse; changing layout keeps its socket and native page mounted. */
function OpenBrowser({
  streamed,
  tabs,
  onComment,
}: {
  streamed: Browse;
  tabs: Browse[];
  onComment?: (comment: PageComment) => void;
}) {
  const close = useBrowserPanelStore((state) => state.close);
  const open = useBrowserPanelStore((state) => state.open);
  const shell = useShell();
  const t = useTranslations("browse");
  const chat = useTranslations("chat");
  const running = isRunning(streamed);
  const live = useLiveBrowse(streamed.runId ?? "", streamed.callId, Boolean(streamed.runId));
  // Only its own browse's copy, and never past the end, where the stream has
  // the outcome and the socket has been let go.
  const mine = running && live.browse?.callId === streamed.callId;
  const browse = withLivePreview(streamed, live.browse);
  const holding = Boolean(browse.heldBy);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      // While a person holds the browser, Escape is a key for the page.
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
              />
            )}
            <div className="min-h-0 flex-1">{content}</div>
          </>
        );
      }}
    </BrowserPanelFrame>
  );
}
