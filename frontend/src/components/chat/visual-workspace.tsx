"use client";

import { useCallback, useId, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Code2, Maximize2, Minimize2, Shapes, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { IconButton, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";
import { PortalContainerContext } from "@/components/ui/portal-container";
import { cn } from "@/lib/utils";
import { ChatPanelResize } from "./chat-panel-resize";
import { useVisualWorkspace } from "./visual-workspace-context";
import { useVisualWorkspaceLayout } from "./use-visual-workspace-layout";

/** One live document across inline, code, docked and expanded views. */
export function VisualWorkspace({
  visualId,
  title,
  content,
  code,
  onCodeChange,
  actions,
  dialogs,
  children,
}: {
  visualId: string;
  title: string;
  content: string;
  code: boolean;
  onCodeChange: (code: boolean) => void;
  actions: ReactNode;
  dialogs?: ReactNode;
  children: ReactNode;
}) {
  const t = useTranslations("chat.visuals");
  const workspace = useVisualWorkspace(visualId);
  const id = useId();
  const layer = useRef<HTMLDivElement | null>(null);
  const [portal, setPortal] = useState<HTMLDivElement | null>(null);
  const ref = useCallback((node: HTMLDivElement | null) => {
    layer.current = node;
    setPortal(node);
  }, []);
  const { bounds, inlineHeight, dismiss } = useVisualWorkspaceLayout(
    layer,
    workspace.slot,
    workspace.open,
    workspace.fullscreen,
    workspace.close,
  );
  const docked = workspace.open && !workspace.fullscreen && bounds !== null;
  const placement: CSSProperties | undefined = workspace.open
    ? docked
      ? { left: bounds.left, top: bounds.top, width: bounds.width, height: bounds.height }
      : { inset: 0, width: "100%", height: "100%" }
    : undefined;
  return (
    <PortalContainerContext.Provider value={workspace.open ? (portal ?? undefined) : undefined}>
      <div style={workspace.open ? { height: inlineHeight } : undefined}>
        <div
          ref={ref}
          id={id}
          popover="manual"
          tabIndex={workspace.open ? -1 : undefined}
          role={workspace.open ? "region" : undefined}
          aria-label={workspace.open ? t("workspaceTitle", { title }) : undefined}
          data-visual-workspace={workspace.open ? (docked ? "docked" : "fullscreen") : "inline"}
          style={{ ...placement, display: workspace.open ? "flex" : "block" }}
          className={cn(
            "relative inset-auto m-0 block w-full max-w-none border-0 p-0 text-inherit outline-none",
            workspace.open
              ? "bg-background fixed z-30 flex min-h-0 min-w-0 flex-col border-l shadow-xl"
              : "bg-transparent",
          )}
        >
          {docked && (
            <ChatPanelResize
              label={t("resizeWorkspace")}
              controls={id}
              width={workspace.width}
              onWidthChange={workspace.setWidth}
              getBounds={() => workspace.slot?.parentElement?.getBoundingClientRect()}
              className="hover:bg-foreground/10 focus-visible:bg-foreground/10 absolute inset-y-0 left-0 z-50 w-2 cursor-col-resize touch-none bg-transparent focus-visible:outline-none"
            />
          )}
          {workspace.open && (
            <header className="flex min-h-14 shrink-0 items-center gap-2 border-b px-4">
              <Shapes className="text-muted-foreground size-4 shrink-0" aria-hidden />
              <h2 className="min-w-0 flex-1 truncate text-sm font-medium">{title}</h2>
              {actions}
              {(docked || workspace.fullscreen) && (
                <IconButton
                  aria-label={workspace.fullscreen ? t("dockWorkspace") : t("fullScreen")}
                  title={workspace.fullscreen ? t("dockWorkspace") : t("fullScreen")}
                  onClick={() => workspace.show(!workspace.fullscreen)}
                >
                  {workspace.fullscreen ? <Minimize2 /> : <Maximize2 />}
                </IconButton>
              )}
              <IconButton aria-label={t("closeWorkspace")} onClick={dismiss}>
                <X />
              </IconButton>
            </header>
          )}
          <Tabs
            value={code ? "code" : "preview"}
            onValueChange={(value) => onCodeChange(value === "code")}
            className={workspace.open ? "flex min-h-0 flex-1 flex-col" : undefined}
          >
            {workspace.open && (
              <TabsList aria-label={t("workspaceViews")} className="shrink-0 px-3">
                <TabsTrigger value="preview">
                  <Shapes className="size-3.5" />
                  {t("previewTab")}
                </TabsTrigger>
                <TabsTrigger value="code">
                  <Code2 className="size-3.5" />
                  {t("codeTab")}
                </TabsTrigger>
              </TabsList>
            )}
            <TabsContent
              forceMount
              hidden={code}
              value="preview"
              className="relative m-0 min-h-0 flex-1"
            >
              {children}
            </TabsContent>
            <TabsContent value="code" className="m-0 min-h-0 flex-1 overflow-auto">
              <pre
                className="bg-foreground/[0.04] h-full max-h-[32rem] scrollbar-thin overflow-auto rounded-xl p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap"
                style={workspace.open ? { maxHeight: "none" } : undefined}
              >
                {content}
              </pre>
            </TabsContent>
          </Tabs>
        </div>
      </div>
      {dialogs}
    </PortalContainerContext.Provider>
  );
}
