"use client";

import { useEffect } from "react";

import { useLiveBrowse } from "@/hooks/use-live-browse";
import { browseById, isRunning, type Browse } from "@/lib/browse";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";
import type { PageComment } from "./browser-comment";
import { BrowserWindow } from "./browser-window";

/**
 * One of the conversation's browses, full screen.
 *
 * A browse lives under the message that started it (`TurnBrowses`); this is where
 * one goes when somebody maximises it, to read a dense page or work in it at the
 * size of the screen. Restoring puts it back under the message. Taking over
 * happens here as it does there - the live socket is this view's while it is open.
 */
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
  return streamed === null ? null : <OpenBrowser streamed={streamed} onComment={onComment} />;
}

/** The full-screen window with a browse in it, as the conversation's stream last drew it. */
function OpenBrowser({
  streamed,
  onComment,
}: {
  streamed: Browse;
  onComment?: (comment: PageComment) => void;
}) {
  const close = useBrowserPanelStore((state) => state.close);
  const running = isRunning(streamed);
  const live = useLiveBrowse(
    streamed.runId ?? "",
    streamed.callId,
    running && Boolean(streamed.runId),
  );
  // Only its own browse's copy, and never past the end, where the stream has
  // the outcome and the socket has been let go.
  const mine = running && live.browse?.callId === streamed.callId;
  const browse = mine && live.browse ? live.browse : streamed;
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
    <aside className="bg-background fixed inset-0 z-50 flex flex-col">
      <BrowserWindow
        // One window per browse: switching which one is open must not carry the
        // last one's state - its remember-this-sign-in tick above all.
        key={streamed.callId}
        waitForFit
        browse={browse}
        control={
          mine && live.status === "live"
            ? { canControl: live.canControl, canRemember: live.canRemember, send: live.send }
            : null
        }
        maximized
        onMaximize={close}
        newTabHref={streamed.runId ? `/browse/${streamed.runId}/${streamed.callId}` : undefined}
        onComment={onComment}
      />
    </aside>
  );
}
