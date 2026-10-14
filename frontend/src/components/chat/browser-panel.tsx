"use client";

import { useCallback, useEffect, useRef } from "react";
import { useTranslations } from "next-intl";

import { useLiveBrowse } from "@/hooks/use-live-browse";
import { browseById, isRunning, type Browse } from "@/lib/browse";
import { cn } from "@/lib/utils";
import {
  MAX_PANEL_WIDTH,
  MIN_PANEL_WIDTH,
  useBrowserPanelStore,
} from "@/stores/browser-panel-store";
import { BrowserWindow } from "./browser-window";

/** How much one arrow key moves the edge, for resizing without a pointer. */
const KEY_STEP = 40;

/** Where the panel docks beside the conversation rather than covering it. */
const DOCKS = "(min-width: 1024px)";

/**
 * The drag handle on the panel's inner edge.
 *
 * Pointer capture rather than window listeners: the pointer leaves this element
 * on the first millimetre of every drag, and `setPointerCapture` is what keeps
 * the events coming to it without a global `mousemove` that has to be torn down
 * on a component that may unmount mid-drag.
 *
 * It is also a `slider` with arrow keys, because a width is a real setting and
 * dragging is not available to everyone.
 */
function ResizeHandle({ width, onResize }: { width: number; onResize: (next: number) => void }) {
  const t = useTranslations("chat");

  const onPointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (event.buttons === 0) return;
      // The panel is pinned to the right edge, so its width is the distance
      // from the pointer to that edge.
      onResize(window.innerWidth - event.clientX);
    },
    [onResize],
  );

  return (
    <div
      role="slider"
      aria-orientation="vertical"
      aria-label={t("browserResize")}
      aria-valuenow={width}
      aria-valuemin={MIN_PANEL_WIDTH}
      aria-valuemax={MAX_PANEL_WIDTH}
      tabIndex={0}
      onPointerDown={(event) => event.currentTarget.setPointerCapture(event.pointerId)}
      onPointerMove={onPointerMove}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft") onResize(width + KEY_STEP);
        if (event.key === "ArrowRight") onResize(width - KEY_STEP);
      }}
      className="hover:bg-foreground/15 focus-visible:bg-foreground/25 absolute inset-y-0 left-0 z-10 hidden w-1.5 cursor-col-resize bg-transparent transition-colors lg:block"
    />
  );
}

/**
 * Opens the panel for a browse the moment it starts, the way a desktop agent
 * shows its browser - once per browse, and only where the panel docks beside the
 * conversation. On a phone it would cover the chat somebody is reading, so there
 * the line in the transcript stays the way in.
 *
 * Remembered per browse rather than per conversation: closing the panel is a
 * decision about that browse, and the next one the agent starts opens again.
 */
function useOpenWhenBrowsing(browses: Browse[], docked: boolean) {
  const open = useBrowserPanelStore((state) => state.open);
  const openCallId = useBrowserPanelStore((state) => state.openCallId);
  const shown = useRef(new Set<string>());

  useEffect(() => {
    const fresh = browses.find((browse) => isRunning(browse) && !shown.current.has(browse.callId));
    if (!fresh) return;
    shown.current.add(fresh.callId);
    if (docked && openCallId === null && window.matchMedia(DOCKS).matches) {
      open(fresh.callId, "panel");
    }
  }, [browses, docked, open, openCallId]);
}

/**
 * The agent's browser beside the conversation.
 *
 * Docked rather than laid over the chat on a wide screen: the transcript narrows
 * and the page takes the right-hand column, so somebody can read what the agent
 * says while watching what it does. On a phone, and when maximised, it takes
 * the screen. Taking over happens here, in the same window - the live socket is
 * opened only while the panel shows a browse that is still running.
 *
 * `docked` false is for a conversation in a small scope (the assistant widget),
 * where there is no column to give up and the panel always takes the screen.
 */
export function BrowserPanel({ browses, docked = true }: { browses: Browse[]; docked?: boolean }) {
  const openCallId = useBrowserPanelStore((state) => state.openCallId);
  useOpenWhenBrowsing(browses, docked);
  // The browse somebody opened, by id - never "the running one". A panel that
  // followed whichever browse advanced last would swap page under a reader the
  // moment the other one moved.
  const streamed = browseById(browses, openCallId);
  // Mounted only with something to show, so a conversation that is not
  // browsing opens no live view and holds no socket for one.
  return streamed === null ? null : <OpenBrowser streamed={streamed} docked={docked} />;
}

/** The panel with a browse in it, as the conversation's stream last drew it. */
function OpenBrowser({ streamed, docked }: { streamed: Browse; docked: boolean }) {
  const mode = useBrowserPanelStore((state) => state.mode);
  const width = useBrowserPanelStore((state) => state.width);
  const open = useBrowserPanelStore((state) => state.open);
  const close = useBrowserPanelStore((state) => state.close);
  const setWidth = useBrowserPanelStore((state) => state.setWidth);
  const running = isRunning(streamed);
  const live = useLiveBrowse(
    streamed.runId ?? "",
    streamed.callId,
    running && Boolean(streamed.runId),
  );
  // The live view's copy while the browse runs: it knows who holds the browser
  // and whether this person may, which the conversation's stream does not say.
  // Only its own browse's copy, and never past the end, where the stream has
  // the outcome and the socket has been let go.
  const mine = running && live.browse?.callId === streamed.callId;
  const browse = mine && live.browse ? live.browse : streamed;
  const full = mode === "full" || !docked;
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
    <aside
      style={{ "--browser-panel-width": `${width}px` } as React.CSSProperties}
      className={cn(
        "bg-background z-50 flex flex-col",
        full
          ? "fixed inset-0"
          : "lg:border-border fixed inset-0 lg:relative lg:inset-auto lg:z-auto lg:h-full lg:w-[var(--browser-panel-width)] lg:max-w-[50%] lg:shrink-0 lg:border-l",
      )}
    >
      {!full && <ResizeHandle width={width} onResize={setWidth} />}
      <BrowserWindow
        waitForFit
        browse={browse}
        control={
          mine && live.status === "live"
            ? { canControl: live.canControl, canRemember: live.canRemember, send: live.send }
            : null
        }
        onClose={close}
        maximized={mode === "full"}
        onMaximize={
          docked ? () => open(streamed.callId, mode === "full" ? "panel" : "full") : undefined
        }
        newTabHref={streamed.runId ? `/browse/${streamed.runId}/${streamed.callId}` : undefined}
      />
    </aside>
  );
}
