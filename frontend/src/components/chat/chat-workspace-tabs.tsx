"use client";

import { FolderOpen, Globe, Shapes } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { useChatWorkspace, type WorkspacePanel } from "./chat-workspace-context";

const PANELS = ["visuals", "browser", "files"] as const;
const ICONS = { visuals: Shapes, browser: Globe, files: FolderOpen };

/** One tab contract across the visual's top layer and the mounted browser/file panes. */
export function ChatWorkspaceTabs({ panel }: { panel: WorkspacePanel }) {
  const t = useTranslations("chat.workspace");
  const workspace = useChatWorkspace();
  if (!workspace?.shared || workspace.activePanel !== panel) return null;
  const available = PANELS.filter((one) =>
    one === "visuals"
      ? workspace.selection !== null
      : one === "browser"
        ? workspace.browserId !== null
        : true,
  );
  return (
    <div
      role="tablist"
      tabIndex={-1}
      aria-label={t("title")}
      data-tour="chat-workspace-tabs"
      className="bg-background flex shrink-0 gap-1 border-b px-3 py-1.5"
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
      {PANELS.map((one) => {
        const Icon = ICONS[one];
        return (
          <button
            key={one}
            type="button"
            role="tab"
            id={`${workspace.id}-tab-${one}`}
            aria-controls={`${workspace.id}-panel-${one}`}
            aria-selected={panel === one}
            disabled={!available.includes(one)}
            tabIndex={panel === one ? 0 : -1}
            onClick={() => workspace.openPanel(one)}
            className={cn(
              "focus-visible:ring-ring inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium focus-visible:ring-2 focus-visible:outline-none disabled:opacity-40",
              panel === one
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:bg-muted/60",
            )}
          >
            <Icon className="size-3.5" aria-hidden />
            {t(one)}
          </button>
        );
      })}
    </div>
  );
}
