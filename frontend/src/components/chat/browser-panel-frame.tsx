"use client";

import { useId, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { Separator } from "@/components/ui/separator";

const MIN_WIDTH = 35;
const MAX_WIDTH = 65;
const INITIAL_WIDTH = 55;
const bounded = (width: number) => Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, width));

/** Dock in the available chat width; narrow chats and explicit expansion use the full screen. */
export function BrowserPanelFrame({
  children,
}: {
  children: (layout: { fullscreen: boolean; toggleFullscreen: () => void }) => ReactNode;
}) {
  const t = useTranslations("chat");
  const id = useId();
  const panel = useRef<HTMLElement>(null);
  const [width, setWidth] = useState(INITIAL_WIDTH);
  const [fullscreen, setFullscreen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const style: CSSProperties & { "--browser-panel-width": string } = {
    "--browser-panel-width": `${width}%`,
  };
  return (
    <aside
      ref={panel}
      id={id}
      aria-label={t("browserHeading")}
      data-browser-panel={fullscreen ? "fullscreen" : "docked"}
      style={style}
      className={cn(
        "bg-background fixed inset-0 z-50 flex min-h-0 min-w-0 flex-col",
        !fullscreen &&
          "@min-[900px]/browser-layout:relative @min-[900px]/browser-layout:inset-auto @min-[900px]/browser-layout:z-20 @min-[900px]/browser-layout:h-full @min-[900px]/browser-layout:w-(--browser-panel-width) @min-[900px]/browser-layout:shrink-0 @min-[900px]/browser-layout:border-l",
      )}
    >
      {!fullscreen && (
        <Separator
          decorative={false}
          orientation="vertical"
          tabIndex={0}
          aria-label={t("browserResize")}
          aria-controls={id}
          aria-valuemin={MIN_WIDTH}
          aria-valuemax={MAX_WIDTH}
          aria-valuenow={Math.round(width)}
          className="hover:bg-foreground/10 focus-visible:bg-foreground/10 absolute inset-y-0 left-0 z-30 hidden w-3 -translate-x-1/2 cursor-col-resize touch-none bg-transparent focus-visible:outline-none @min-[900px]/browser-layout:block"
          onKeyDown={(event) => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
            event.preventDefault();
            setWidth((current) =>
              event.key === "Home"
                ? MIN_WIDTH
                : event.key === "End"
                  ? MAX_WIDTH
                  : bounded(current + (event.key === "ArrowLeft" ? 2 : -2)),
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
              setWidth(bounded(((bounds.right - event.clientX) / bounds.width) * 100));
          }}
          onPointerUp={() => setDragging(false)}
          onPointerCancel={() => setDragging(false)}
          onLostPointerCapture={() => setDragging(false)}
          onDoubleClick={() => setWidth(INITIAL_WIDTH)}
        />
      )}
      {dragging && (
        <div data-native-browser-blocked className="fixed inset-0 z-40 cursor-col-resize" />
      )}
      {children({ fullscreen, toggleFullscreen: () => setFullscreen((current) => !current) })}
    </aside>
  );
}
