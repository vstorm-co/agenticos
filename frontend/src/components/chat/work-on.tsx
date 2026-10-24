"use client";

import { useEffect, useState } from "react";
import { Cloud, FolderOpen, Laptop, X } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  useDeviceLink,
  useDeviceStatus,
  useLocalFolders,
  useLocalServices,
} from "@/hooks/use-desktop";
import { isDesktopShell } from "@/lib/desktop/shell";
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
  const shell = useShell();
  return isDesktopShell(shell) ? <ComputerWorkOn /> : null;
}

function ComputerWorkOn() {
  const t = useTranslations("chat.controls.workOn");
  const { data: device } = useDeviceStatus();
  const { link } = useDeviceLink();
  const { state, pick, revoke } = useLocalFolders();
  const services = useLocalServices().state.data ?? [];
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

  const linked = device?.linked === true;
  const grants = state.data?.grants ?? [];
  const modes = state.data?.modes ?? [];
  const selectedMode = modes.includes(newMode) ? newMode : (modes[0] ?? "read_only");

  const chooseCloud = () => {
    setChoosingFor(undefined);
    setTarget(conversationId, null);
  };

  const chooseComputer = () => {
    if (linked) {
      setChoosingFor(conversationId);
      return;
    }
    link.mutate(undefined, {
      onSuccess: (status) => {
        if (status.linked) setChoosingFor(conversationId);
      },
    });
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
              onClick: chooseComputer,
            },
          ] as const
        ).map(({ key, icon: Icon, active, onClick }) => (
          <button
            key={key}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={link.isPending || (key === "computer" && device === undefined)}
            aria-busy={key === "computer" && link.isPending}
            onClick={onClick}
            className={cn(
              "inline-flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-medium transition-colors",
              active
                ? "bg-foreground/[0.06] text-foreground"
                : "text-foreground/70 hover:bg-foreground/[0.04]",
              "disabled:cursor-wait disabled:opacity-45",
            )}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden />
            {t(key === "computer" && link.isPending ? "linking" : key)}
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
                        setTarget(conversationId, {
                          ...target,
                          folder: grant.path,
                          mode: grant.mode,
                        })
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
          {target !== null && (
            <label className="flex min-h-10 items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={target.browser ?? false}
                onChange={(event) =>
                  setTarget(conversationId, { ...target, browser: event.target.checked })
                }
              />
              {t("localBrowser")}
            </label>
          )}
          {target !== null && (
            <p className="text-muted-foreground text-xs leading-relaxed">{t("accessHint")}</p>
          )}
          {target !== null && services.length > 0 && (
            <div className="space-y-2 py-2">
              <label className="block text-xs">
                {t("model")}
                <select
                  aria-label={t("model")}
                  value={target.model_service ?? ""}
                  className="border-input bg-background mt-1 h-10 w-full rounded-md border px-2"
                  onChange={(event) =>
                    setTarget(conversationId, {
                      ...target,
                      model_service: event.target.value || null,
                    })
                  }
                >
                  <option value="">{t("agentModel")}</option>
                  {services
                    .filter((service) => service.kind === "model")
                    .map((service) => (
                      <option key={service.id} value={service.id}>
                        {service.name} · {service.model}
                      </option>
                    ))}
                </select>
              </label>
              {(target.mcp_services?.length ?? 0) >= 8 && (
                <p className="text-muted-foreground text-xs">{t("mcpLimit")}</p>
              )}
              {services
                .filter((service) => service.kind === "mcp")
                .map((service) => (
                  <label key={service.id} className="flex min-h-10 items-center gap-2 text-xs">
                    <input
                      type="checkbox"
                      checked={(target.mcp_services ?? []).includes(service.id)}
                      disabled={
                        (target.mcp_services?.length ?? 0) >= 8 &&
                        !(target.mcp_services ?? []).includes(service.id)
                      }
                      onChange={(event) =>
                        setTarget(conversationId, {
                          ...target,
                          mcp_services: event.target.checked
                            ? [...(target.mcp_services ?? []), service.id]
                            : (target.mcp_services ?? []).filter((id) => id !== service.id),
                        })
                      }
                    />
                    {service.name}
                  </label>
                ))}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-1 pt-1">
            {modes.map((mode) => (
              <button
                key={mode}
                type="button"
                aria-pressed={selectedMode === mode}
                onClick={() => setNewMode(mode)}
                title={t(`modeHint.${mode}`)}
                className={cn(
                  "rounded-lg px-2 py-1 text-xs transition-colors",
                  selectedMode === mode
                    ? "bg-foreground/[0.06] text-foreground"
                    : "text-muted-foreground hover:bg-foreground/[0.04]",
                )}
              >
                {t(`mode.${mode}`)}
              </button>
            ))}
            <button
              type="button"
              disabled={pick.isPending || modes.length === 0}
              onClick={() =>
                pick.mutate(selectedMode, {
                  onSuccess: (grant) => {
                    if (grant)
                      setTarget(conversationId, {
                        ...target,
                        folder: grant.path,
                        mode: grant.mode,
                      });
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
