"use client";

import { useId, useRef, type CSSProperties, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { ChatPanelResize } from "./chat-panel-resize";
import { ChatWorkspaceBoundary, useRequiredChatWorkspace } from "./chat-workspace-context";
import { ChatWorkspaceTabs } from "./chat-workspace-tabs";

interface FrameProps {
  panel?: "browser" | "files";
  children: (layout: { fullscreen: boolean; toggleFullscreen: () => void }) => ReactNode;
}

/** Dock in the available chat width; narrow chats and explicit expansion use the full screen. */
export function ChatWorkspaceFrame(props: FrameProps) {
  return (
    <ChatWorkspaceBoundary>
      <Frame {...props} />
    </ChatWorkspaceBoundary>
  );
}

function Frame({ children, panel: kind = "browser" }: FrameProps) {
  const t = useTranslations("chat");
  const ownId = useId();
  const panel = useRef<HTMLElement>(null);
  const workspace = useRequiredChatWorkspace();
  const { width, setWidth, fullscreen, setFullscreen } = workspace;
  const visible = !workspace.shared || workspace.activePanel === kind;
  const id = workspace.shared ? `${workspace.id}-panel-${kind}` : ownId;
  const style: CSSProperties & { "--browser-panel-width": string } = {
    "--browser-panel-width": `${width}%`,
    display: visible ? undefined : "none",
  };
  return (
    <aside
      ref={panel}
      id={id}
      role={workspace.shared ? "tabpanel" : undefined}
      aria-label={t(kind === "browser" ? "browserHeading" : "files.title")}
      aria-labelledby={workspace.shared ? `${workspace.id}-tab-${kind}` : undefined}
      inert={!visible}
      data-browser-panel={kind === "browser" ? (fullscreen ? "fullscreen" : "docked") : undefined}
      data-workspace-panel={kind}
      data-native-browser-blocked={kind === "files" && visible ? "" : undefined}
      style={style}
      className={cn(
        "bg-background fixed inset-0 z-50 flex min-h-0 min-w-0 flex-col",
        !fullscreen &&
          "@min-[1000px]/browser-layout:relative @min-[1000px]/browser-layout:inset-auto @min-[1000px]/browser-layout:z-20 @min-[1000px]/browser-layout:h-full @min-[1000px]/browser-layout:w-(--browser-panel-width) @min-[1000px]/browser-layout:shrink-0 @min-[1000px]/browser-layout:border-l",
      )}
    >
      {!fullscreen && (
        <ChatPanelResize
          label={t("workspace.resize")}
          controls={id}
          width={width}
          onWidthChange={setWidth}
          getBounds={() => panel.current?.parentElement?.getBoundingClientRect()}
          className="hover:bg-foreground/10 focus-visible:bg-foreground/10 absolute inset-y-0 left-0 z-30 hidden w-3 -translate-x-1/2 cursor-col-resize touch-none bg-transparent focus-visible:outline-none @min-[1000px]/browser-layout:block"
        />
      )}
      <ChatWorkspaceTabs panel={kind} />
      {children({ fullscreen, toggleFullscreen: () => setFullscreen(!fullscreen) })}
    </aside>
  );
}
