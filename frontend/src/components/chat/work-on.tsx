"use client";

import { useEffect, useState } from "react";
import { Cloud, FolderOpen, Laptop, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { useDeviceStatus, useLocalFolders } from "@/hooks/use-desktop";
import { useShell } from "@/hooks/use-shell";
import type { LocalMode } from "@/lib/desktop/commands";
import { cn } from "@/lib/utils";
import { useConversationStore } from "@/stores";
import { useWorkOnStore } from "@/stores/work-on-store";

/** The last part of a path, which is what a person recognises a folder by. */
function folderName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).at(-1) ?? path;
}

/**
 * "Work on: Cloud / This computer" - where this conversation's runs work (#2305).
 *
 * Only in the desktop app, which is the only place that can pick a folder and
 * carry the work out. Cloud is the agent's own sandbox; this computer is a folder
 * the person picks in the native dialog, with the mode they allow there. The
 * choice is remembered per conversation, and a new chat starts in the cloud.
 */
export function WorkOn() {
  const t = useTranslations("chat.controls.workOn");
  const shell = useShell();
  const { data: device } = useDeviceStatus();
  const { state, pick, revoke } = useLocalFolders();
  const conversationId = useConversationStore((store) => store.currentConversationId);
  const target = useWorkOnStore((store) => store.targetFor(conversationId));
  const setTarget = useWorkOnStore((store) => store.set);
  const adopt = useWorkOnStore((store) => store.adopt);
  // "This computer" chosen before a folder is: held for this conversation only.
  const [choosingFor, setChoosingFor] = useState<string | null | undefined>(undefined);
  const onComputer = target !== null || choosingFor === conversationId;
  const [newMode, setNewMode] = useState<LocalMode>("workspace_write");

  // A new chat's choice files itself under the id the server gives it.
  useEffect(() => {
    if (conversationId !== null) adopt(conversationId);
  }, [conversationId, adopt]);

  if (shell === null) return null;
  const linked = device?.linked === true;
  const grants = state.data?.grants ?? [];
  const modes = state.data?.modes ?? [];

  const chooseCloud = () => {
    setChoosingFor(undefined);
    setTarget(conversationId, null);
  };

  return (
    <div className="border-foreground/10 mt-4 border-t pt-4">
      <p className="text-muted-foreground mb-3 text-xs leading-relaxed">{t("title")}</p>
      <div role="radiogroup" aria-label={t("title")} className="grid grid-cols-2 gap-1">
        {(
          [
            { key: "cloud", icon: Cloud, active: !onComputer, onClick: chooseCloud },
            {
              key: "computer",
              icon: Laptop,
              active: onComputer,
              onClick: () => setChoosingFor(conversationId),
            },
          ] as const
        ).map(({ key, icon: Icon, active, onClick }) => (
          <button
            key={key}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={key === "computer" && !linked}
            onClick={onClick}
            className={cn(
              "inline-flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-medium transition-colors",
              active
                ? "bg-foreground/[0.06] text-foreground"
                : "text-foreground/70 hover:bg-foreground/[0.04]",
              key === "computer" && !linked && "cursor-not-allowed opacity-45",
            )}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden />
            {t(key)}
          </button>
        ))}
      </div>
      {!linked && <p className="text-muted-foreground mt-2 text-xs">{t("notLinked")}</p>}
      {linked && device?.connected === false && (
        <p className="text-muted-foreground mt-2 text-xs">{t("offline")}</p>
      )}

      {onComputer && linked && (
        <div className="mt-3 space-y-1">
          {grants.length > 0 && (
            <div role="radiogroup" aria-label={t("folders")} className="space-y-1">
              {grants.map((grant) => {
                const active = target?.folder === grant.path;
                return (
                  <div
                    key={grant.path}
                    className={cn(
                      "flex items-center gap-2 rounded-xl px-3 py-2 transition-colors",
                      active ? "bg-foreground/[0.06]" : "hover:bg-foreground/[0.04]",
                    )}
                  >
                    <button
                      type="button"
                      role="radio"
                      aria-checked={active}
                      onClick={() =>
                        setTarget(conversationId, { folder: grant.path, mode: grant.mode })
                      }
                      className="min-w-0 flex-1 text-left"
                      title={grant.path}
                    >
                      <span className="text-foreground block truncate text-xs font-medium">
                        {folderName(grant.path)}
                      </span>
                      <span className="text-muted-foreground block text-xs">
                        {t(`mode.${grant.mode}`)}
                      </span>
                    </button>
                    <button
                      type="button"
                      aria-label={t("revoke", { folder: folderName(grant.path) })}
                      onClick={() => {
                        if (active) setTarget(conversationId, null);
                        revoke.mutate(grant.path);
                      }}
                      className="text-muted-foreground hover:text-foreground rounded p-1"
                    >
                      <X className="h-3.5 w-3.5" aria-hidden />
                    </button>
                  </div>
                );
              })}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-1 pt-1">
            {modes.map((mode) => (
              <button
                key={mode}
                type="button"
                aria-pressed={newMode === mode}
                onClick={() => setNewMode(mode)}
                title={t(`modeHint.${mode}`)}
                className={cn(
                  "rounded-lg px-2 py-1 text-xs transition-colors",
                  newMode === mode
                    ? "bg-foreground/[0.06] text-foreground"
                    : "text-muted-foreground hover:bg-foreground/[0.04]",
                )}
              >
                {t(`mode.${mode}`)}
              </button>
            ))}
            <button
              type="button"
              disabled={pick.isPending}
              onClick={() =>
                pick.mutate(newMode, {
                  onSuccess: (grant) => {
                    if (grant) setTarget(conversationId, { folder: grant.path, mode: grant.mode });
                  },
                })
              }
              className="text-foreground hover:bg-foreground/[0.04] ml-auto inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium"
            >
              <FolderOpen className="h-3.5 w-3.5" aria-hidden />
              {t("pick")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
