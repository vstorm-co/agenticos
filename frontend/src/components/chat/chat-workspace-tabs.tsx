"use client";

import { FolderOpen, Globe, Maximize2, Minimize2, Monitor, Shapes, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { IconButton } from "@/components/ui";
import { cn } from "@/lib/utils";
import { useChatWorkspace, type WorkspacePanel } from "./chat-workspace-context";

const PANELS = ["visuals", "browser", "desktop", "files"] as const;
const ICONS = { visuals: Shapes, browser: Globe, desktop: Monitor, files: FolderOpen };

/** One tab contract across the visual's top layer and the mounted browser/file panes. */
export function ChatWorkspaceTabs({
  panel,
  canExpand = true,
}: {
  panel: WorkspacePanel;
  canExpand?: boolean;
}) {
  const t = useTranslations("chat.workspace");
  const workspace = useChatWorkspace();
  if (!workspace?.shared || workspace.activePanel !== panel) return null;
  const available = PANELS.filter((one) =>
    one === "visuals"
      ? workspace.selection !== null
      : one === "browser"
        ? workspace.browserId !== null || workspace.environmentPanels.includes("browser")
        : one === "desktop"
          ? workspace.environmentPanels.includes("desktop")
          : true,
  );
  return (
    <header className="bg-muted/25 flex min-w-0 shrink-0 items-center gap-1 border-b px-1.5">
      <div
        role="tablist"
        tabIndex={-1}
        aria-label={t("title")}
        data-tour="chat-workspace-tabs"
        className="flex min-w-0 flex-1 gap-1 overflow-x-auto py-1.5"
        onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          const current = available.indexOf(panel);
          const index =
            event.key === "Home"
              ? 0
              : event.key === "End"
                ? available.length - 1
                : (current + (event.key === "ArrowRight" ? 1 : -1) + available.length) %
                  available.length;
          const next = available[index]!;
          workspace.openPanel(next);
          requestAnimationFrame(() =>
            document.getElementById(`${workspace.id}-tab-${next}`)?.focus(),
          );
        }}
      >
        {available.map((one) => {
          const Icon = ICONS[one];
          return (
            <button
              key={one}
              type="button"
              role="tab"
              id={`${workspace.id}-tab-${one}`}
              aria-controls={`${workspace.id}-panel-${one}`}
              aria-selected={panel === one}
              tabIndex={panel === one ? 0 : -1}
              onClick={() => workspace.openPanel(one)}
              className={cn(
                "focus-visible:ring-ring inline-flex shrink-0 items-center gap-2 rounded-lg border border-transparent px-3 py-2 text-xs font-medium focus-visible:ring-2 focus-visible:outline-none pointer-coarse:min-h-11",
                panel === one
                  ? "border-border bg-background text-foreground shadow-xs"
                  : "text-muted-foreground hover:bg-muted/60",
              )}
            >
              <Icon className="size-3.5" aria-hidden />
              {t(one)}
            </button>
          );
        })}
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {canExpand && (
          <IconButton
            className="size-9 pointer-coarse:size-11"
            aria-label={t(workspace.fullscreen ? "dock" : "expand")}
            title={t(workspace.fullscreen ? "dock" : "expand")}
            onClick={() => workspace.setFullscreen(!workspace.fullscreen)}
          >
            {workspace.fullscreen ? <Minimize2 /> : <Maximize2 />}
          </IconButton>
        )}
        <IconButton
          className="size-9 pointer-coarse:size-11"
          aria-label={t("close")}
          title={t("close")}
          onClick={workspace.close}
        >
          <X />
        </IconButton>
      </div>
    </header>
  );
}
