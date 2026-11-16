"use client";

import { Globe, Monitor, Settings2 } from "lucide-react";
import { useTranslations } from "next-intl";
import type { Ref } from "react";

import { cn } from "@/lib/utils";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";
import { useSourcesPanelStore } from "@/stores/sources-panel-store";

/** Opening a workspace pane changes only this chat's UI state. */
export function WorkspaceRail({
  filesSlot,
  hasAgent = false,
  panelIds,
}: {
  filesSlot: Ref<HTMLSpanElement>;
  hasAgent?: boolean;
  panelIds: Record<"browser" | "computer" | "settings", string>;
}) {
  const t = useTranslations("chat.workspace");
  const settings = useTranslations("chat.agentSettings");
  const surface = useBrowserPanelStore((state) => state.surface);
  const open = useBrowserPanelStore((state) => state.openSurface);
  const close = useBrowserPanelStore((state) => state.close);
  const closeSources = useSourcesPanelStore((state) => state.close);
  return (
    <nav
      aria-label={t("rail")}
      data-tour="chat-workspace"
      className="border-border bg-background z-20 hidden w-12 shrink-0 flex-col items-center gap-2 border-l px-1 py-3 lg:flex"
    >
      {(["browser", "computer"] as const).map((kind) => {
        const Icon = kind === "browser" ? Globe : Monitor;
        const label = t(kind === "browser" ? "openBrowser" : "openComputer");
        return (
          <button
            key={kind}
            type="button"
            aria-label={label}
            title={label}
            aria-expanded={surface === kind}
            aria-controls={panelIds[kind]}
            onClick={() => {
              closeSources();
              if (surface === kind) close();
              else open(kind);
            }}
            className={cn(
              "text-muted-foreground hover:text-foreground hover:bg-accent/60 flex size-11 items-center justify-center rounded-lg transition-colors @min-[900px]/browser-layout:size-9",
              surface === kind && "bg-foreground/[0.06] text-foreground",
            )}
          >
            <Icon className="size-4" aria-hidden />
          </button>
        );
      })}
      <span
        ref={filesSlot}
        className="flex size-11 items-center justify-center @min-[900px]/browser-layout:size-9"
      />
      {hasAgent && (
        <button
          type="button"
          data-tour="chat-agent-settings"
          aria-label={settings("open")}
          title={settings("open")}
          aria-expanded={surface === "settings"}
          aria-controls={panelIds.settings}
          onClick={() => {
            closeSources();
            if (surface === "settings") close();
            else open("settings");
          }}
          className={cn(
            "text-muted-foreground hover:text-foreground hover:bg-accent/60 flex size-11 items-center justify-center rounded-lg transition-colors @min-[900px]/browser-layout:size-9",
            surface === "settings" && "bg-foreground/[0.06] text-foreground",
          )}
        >
          <Settings2 className="size-4" aria-hidden />
        </button>
      )}
    </nav>
  );
}
