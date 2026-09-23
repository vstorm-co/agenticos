"use client";

import { useCallback, useEffect, useRef } from "react";
import { Globe, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { browseById, isRunning, type Browse } from "@/lib/browse";
import { cn } from "@/lib/utils";
import {
  MAX_PANEL_WIDTH,
  MIN_PANEL_WIDTH,
  useBrowserPanelStore,
} from "@/stores/browser-panel-store";
import { Outcome, StepRow, Viewport } from "./browser-view";

/** How much one arrow key moves the edge, for resizing without a pointer. */
const KEY_STEP = 40;

/**
 * The drag handle on the panel's inner edge.
 *
 * Pointer capture rather than window listeners: the pointer leaves this element
 * on the first millimetre of every drag, and `setPointerCapture` is what keeps
 * the events coming to it without a global `mousemove` that has to be torn down
 * on a component that may unmount mid-drag.
 *
 * It is also a `separator` with arrow keys, because a width is a real setting
 * and dragging is not available to everyone.
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
      // `slider`, not `separator`: this is a control that sets a value, it
      // reports one through `aria-valuenow`, and the arrow keys change it. A
      // separator that happens to be draggable is the other thing - and it is
      // also what the a11y lint refuses to let take focus.
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
      className="hover:bg-brand/30 focus-visible:bg-brand/40 absolute inset-y-0 left-0 w-1.5 cursor-col-resize bg-transparent transition-colors"
    />
  );
}

/**
 * What the agent's browser is doing, at the size of a window.
 *
 * The expansion of `BrowserCard`, not a thing that opens itself: the card is how
 * a browse appears, and this is what somebody asks for when the thumbnail is too
 * small to read. Closing it returns to the card, which is why there is no
 * dismissed-browse bookkeeping here - nothing was taken away.
 *
 * **The steps are a list, not a transcript.** Each row is what was chosen and how
 * sure the engine was, which is the pair that says whether a browse is worth
 * looking into. The page's own words appear only as an element's label and as
 * the outcome's detail, both rendered as text.
 */
export function BrowserPanel({ browses }: { browses: Browse[] }) {
  const t = useTranslations("chat");
  const openCallId = useBrowserPanelStore((state) => state.openCallId);
  const mode = useBrowserPanelStore((state) => state.mode);
  const width = useBrowserPanelStore((state) => state.width);
  const close = useBrowserPanelStore((state) => state.close);
  const setWidth = useBrowserPanelStore((state) => state.setWidth);
  // The browse somebody opened, by id - never "the running one". A panel that
  // followed whichever browse advanced last would swap page under a reader the
  // moment the other one moved.
  const browse = browseById(browses, openCallId);
  const scroller = useRef<HTMLDivElement>(null);
  const full = mode === "full";

  useEffect(() => {
    if (browse === null) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [browse, close]);

  if (browse === null) return null;

  return (
    <aside
      aria-label={t("browserHeading")}
      // Full screen takes the window and reads a page; the panel takes an edge
      // and watches a browse beside the conversation. Only the second has a
      // width to drag, so only the second carries the handle.
      style={full ? undefined : { width }}
      className={cn(
        "bg-popover fixed z-50 flex flex-col shadow-2xl",
        full ? "inset-0 h-full w-full" : "border-border top-0 right-0 h-full border-l",
      )}
    >
      {!full && <ResizeHandle width={width} onResize={setWidth} />}

      <div className="border-foreground/8 flex items-center justify-between gap-2 border-b px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <Globe className="text-foreground/40 h-4 w-4 shrink-0" aria-hidden />
          <div className="min-w-0">
            <h2 className="text-foreground truncate text-sm font-semibold">
              {browse.title || t("browserHeading")}
            </h2>
            {browse.url && (
              <p className="text-foreground/45 truncate font-mono text-[10px]" title={browse.url}>
                {browse.url}
              </p>
            )}
          </div>
        </div>
        <button
          type="button"
          onClick={close}
          aria-label={t("browserClose")}
          className="text-foreground/50 hover:text-foreground hover:bg-foreground/8 shrink-0 rounded-md p-1 transition-colors"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div
        ref={scroller}
        className={cn(
          "flex-1 scrollbar-thin overflow-y-auto px-4 py-4",
          full ? "mx-auto w-full max-w-5xl space-y-5" : "space-y-4",
        )}
      >
        {browse.goal && (
          <p className="text-foreground/60 text-xs leading-relaxed">
            <span className="text-foreground/40 font-mono text-[10px] tracking-wider uppercase">
              {t("browserGoal")}
            </span>
            <br />
            {browse.goal}
          </p>
        )}

        <Viewport browse={browse} />
        <Outcome browse={browse} />

        {browse.steps.length > 0 && (
          <section className="space-y-1">
            <h3 className="text-foreground/45 px-2 font-mono text-[10px] tracking-wider uppercase">
              {t("browserSteps")}
            </h3>
            <ul className="space-y-0.5">
              {browse.steps.map((step, index) => (
                <StepRow
                  key={step.step}
                  step={step}
                  last={index === browse.steps.length - 1 && isRunning(browse)}
                />
              ))}
            </ul>
          </section>
        )}
      </div>
    </aside>
  );
}
