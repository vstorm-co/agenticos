"use client";

import { useId, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { ChatPanelResize, CHAT_PANEL_INITIAL_WIDTH } from "./chat-panel-resize";

/** Dock in the available chat width; narrow chats and explicit expansion use the full screen. */
export function BrowserPanelFrame({
  children,
}: {
  children: (layout: { fullscreen: boolean; toggleFullscreen: () => void }) => ReactNode;
}) {
  const t = useTranslations("chat");
  const id = useId();
  const panel = useRef<HTMLElement>(null);
  const [width, setWidth] = useState(CHAT_PANEL_INITIAL_WIDTH);
  const [fullscreen, setFullscreen] = useState(false);
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
        <ChatPanelResize
          label={t("browserResize")}
          controls={id}
          width={width}
          onWidthChange={setWidth}
          getBounds={() => panel.current?.parentElement?.getBoundingClientRect()}
          className="hover:bg-foreground/10 focus-visible:bg-foreground/10 absolute inset-y-0 left-0 z-30 hidden w-3 -translate-x-1/2 cursor-col-resize touch-none bg-transparent focus-visible:outline-none @min-[900px]/browser-layout:block"
        />
      )}
      {children({ fullscreen, toggleFullscreen: () => setFullscreen((current) => !current) })}
    </aside>
  );
}
