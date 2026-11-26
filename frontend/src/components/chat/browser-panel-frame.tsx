"use client";

import { useEffect, useId, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { Separator } from "@/components/ui/separator";

export type PanelSizing = "wide" | "sources";
const SOURCES_CAP_PERCENT = 38;
const WIDTHS = {
  wide: { min: 35, max: 65, initial: 55, step: 2 },
  sources: { min: 360, max: 420, initial: 400, step: 16 },
} as const;

/** Dock in the available chat width; narrow chats and explicit expansion use the full screen. */
export function BrowserPanelFrame({
  children,
  label,
  contained = false,
  panelId,
  layout = "browser",
  sizing = "wide",
}: {
  children: (layout: { fullscreen: boolean; toggleFullscreen: () => void }) => ReactNode;
  label?: string;
  contained?: boolean;
  panelId?: string;
  layout?: "browser" | "sources";
  sizing?: PanelSizing;
}) {
  const t = useTranslations("chat");
  const id = useId();
  const panel = useRef<HTMLElement>(null);
  const limits = WIDTHS[sizing];
  const [dockWidth, setDockWidth] = useState<number | null>(null);
  useEffect(() => {
    const dock = panel.current?.parentElement;
    if (!dock || contained || sizing !== "sources") return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setDockWidth(entry.contentRect.width);
    });
    observer.observe(dock);
    return () => observer.disconnect();
  }, [contained, sizing]);
  const maxWidth =
    sizing === "sources" && dockWidth !== null
      ? Math.min(limits.max, (dockWidth * SOURCES_CAP_PERCENT) / 100)
      : limits.max;
  const bounded = (width: number) => Math.min(maxWidth, Math.max(limits.min, width));
  const [width, setWidth] = useState<number>(limits.initial);
  const visibleWidth = Math.min(width, maxWidth);
  const [fullscreen, setFullscreen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const style: CSSProperties & { "--browser-panel-width": string } = {
    "--browser-panel-width":
      sizing === "sources" ? `min(${width}px, ${SOURCES_CAP_PERCENT}%)` : `${width}%`,
  };
  return (
    <aside
      ref={panel}
      id={panelId ?? id}
      aria-label={label ?? t("browserHeading")}
      data-browser-panel={fullscreen ? "fullscreen" : "docked"}
      style={style}
      className={cn(
        "bg-card fixed inset-0 z-50 flex min-h-0 min-w-0 flex-col",
        contained && "absolute",
        !fullscreen &&
          !contained &&
          (layout === "browser"
            ? "@min-[900px]/browser-layout:relative @min-[900px]/browser-layout:inset-auto @min-[900px]/browser-layout:z-20 @min-[900px]/browser-layout:h-full @min-[900px]/browser-layout:w-(--browser-panel-width) @min-[900px]/browser-layout:shrink-0 @min-[900px]/browser-layout:border-l"
            : "@min-[900px]/sources-layout:relative @min-[900px]/sources-layout:inset-auto @min-[900px]/sources-layout:z-20 @min-[900px]/sources-layout:h-full @min-[900px]/sources-layout:w-(--browser-panel-width) @min-[900px]/sources-layout:shrink-0 @min-[900px]/sources-layout:border-l"),
      )}
    >
      {!fullscreen && !contained && (
        <Separator
          decorative={false}
          orientation="vertical"
          tabIndex={0}
          aria-label={t("browserResize")}
          aria-controls={panelId ?? id}
          aria-valuemin={Math.min(limits.min, Math.round(maxWidth))}
          aria-valuemax={Math.round(maxWidth)}
          aria-valuenow={Math.round(visibleWidth)}
          className={cn(
            "hover:bg-foreground/10 focus-visible:bg-foreground/10 absolute inset-y-0 left-0 z-30 hidden w-3 -translate-x-1/2 cursor-col-resize touch-none bg-transparent focus-visible:outline-none",
            // A narrower Sources dock cannot resize: its 38% cap binds even at 360px.
            layout === "browser"
              ? "@min-[900px]/browser-layout:block"
              : "@min-[948px]/sources-layout:block",
          )}
          onKeyDown={(event) => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
            event.preventDefault();
            setWidth(
              event.key === "Home"
                ? limits.min
                : event.key === "End"
                  ? maxWidth
                  : bounded(
                      visibleWidth + (event.key === "ArrowLeft" ? limits.step : -limits.step),
                    ),
            );
          }}
          onPointerDown={(event) => {
            if (event.button !== 0) return;
            event.preventDefault();
            event.currentTarget.setPointerCapture(event.pointerId);
            setDragging(true);
          }}
          onPointerMove={(event) => {
            if (!dragging) return;
            const bounds = panel.current?.parentElement?.getBoundingClientRect();
            if (bounds && bounds.width > 0)
              setWidth(
                bounded(
                  sizing === "sources"
                    ? bounds.right - event.clientX
                    : ((bounds.right - event.clientX) / bounds.width) * 100,
                ),
              );
          }}
          onPointerUp={() => setDragging(false)}
          onPointerCancel={() => setDragging(false)}
          onLostPointerCapture={() => setDragging(false)}
          onDoubleClick={() => setWidth(limits.initial)}
        />
      )}
      {dragging && (
        <div data-native-browser-blocked className="fixed inset-0 z-40 cursor-col-resize" />
      )}
      {children({ fullscreen, toggleFullscreen: () => setFullscreen((current) => !current) })}
    </aside>
  );
}
