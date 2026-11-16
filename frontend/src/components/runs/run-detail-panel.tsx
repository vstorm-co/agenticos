"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";

import { FocusedRun } from "@/components/runs/focused-run";
import { useResizablePanel } from "@/hooks";
import { cn } from "@/lib/utils";

const DEFAULT_WIDTH = 560;
const MIN_WIDTH = 380;
const MAX_WIDTH = 1200;
const STORAGE_KEY = "runDetailPanelWidth";
/** How far one arrow press moves the boundary. */
const KEYBOARD_STEP = 32;

/** Resizable inspector alongside history; both panes fill the Activity viewport. */
export function RunDetailPanel({
  runId,
  onFocusRun,
}: {
  runId: string;
  onFocusRun: (runId: string | null) => void;
}) {
  const t = useTranslations("pages.runs");
  const { width, isDragging, onMouseDown, resizeBy } = useResizablePanel({
    storageKey: STORAGE_KEY,
    defaultWidth: DEFAULT_WIDTH,
    min: MIN_WIDTH,
    max: MAX_WIDTH,
  });

  useEffect(() => {
    // What a reader presses to put a panel away. It was free while this was a
    // dialog; a panel in the page layout has to say so itself.
    function dismiss(event: KeyboardEvent) {
      if (event.key === "Escape") onFocusRun(null);
    }
    window.addEventListener("keydown", dismiss);
    return () => window.removeEventListener("keydown", dismiss);
  }, [onFocusRun]);

  return (
    <aside
      aria-label={t("runDetail")}
      // Through a custom property rather than `style={{ width }}`, so the width
      // applies at the breakpoint where there are two columns and nowhere else.
      style={{ "--run-panel-width": `${width}px` } as React.CSSProperties}
      // A definite parent height keeps the header visible while the body scrolls.
      className="border-border bg-card @container relative flex h-full w-full shrink-0 flex-col overflow-hidden rounded-xl border lg:w-[var(--run-panel-width)]"
    >
      {/* The boundary. A button rather than a bare `separator`, because it is a
          control: the arrow keys move it in steps, so the panel is sizeable by
          somebody who never touches the mouse - which is who would be reading a
          long transcript in it. Hidden below `lg` for the same reason the width
          is: there is only one column down there to drag against. */}
      <button
        type="button"
        aria-label={t("resizeRunDetail")}
        onMouseDown={onMouseDown}
        onKeyDown={(event) => {
          if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
          // Left widens: the panel's left edge is the boundary, so moving it
          // left gives the panel the room the list gives up.
          event.preventDefault();
          event.stopPropagation();
          resizeBy(event.key === "ArrowLeft" ? KEYBOARD_STEP : -KEYBOARD_STEP);
        }}
        className={cn(
          "group absolute top-0 left-0 z-20 hidden h-full w-1.5 cursor-col-resize lg:block",
          "focus-visible:bg-primary/40 focus-visible:outline-none",
          isDragging && "bg-foreground/20",
        )}
      >
        <span className="bg-foreground/0 group-hover:bg-foreground/15 absolute top-1/2 left-1/2 h-12 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full transition-colors" />
      </button>

      <FocusedRun runId={runId} onFocusRun={onFocusRun} onClose={() => onFocusRun(null)} />
    </aside>
  );
}
