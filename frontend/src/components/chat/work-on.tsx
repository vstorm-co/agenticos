"use client";

import { useId } from "react";
import { useMutation } from "@tanstack/react-query";
import { ChevronDown, Cloud, FolderOpen, Globe, Laptop, X } from "lucide-react";
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
import { Button } from "@/components/ui/button";
import { useConversationStore } from "@/stores";
import { useWorkOnStore, type LocalTarget } from "@/stores/work-on-store";

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
  return isDesktopShell(shell) ? (
    <>
      <BrowserWorkOn />
      <ComputerWorkOn />
    </>
  ) : null;
}

function BrowserWorkOn() {
  const t = useTranslations("chat.controls.workOn");
  const conversationId = useConversationStore((state) => state.currentConversationId);
  const local = useWorkOnStore((state) => state.browserFor(conversationId));
  const setBrowser = useWorkOnStore((state) => state.setBrowser);
  const { data: device } = useDeviceStatus();
  const { link } = useDeviceLink();
  const selection = useMutation({
    mutationFn: async (choice: { conversationId: string | null; linked: boolean }) =>
      choice.linked || (await link.mutateAsync()).linked,
    onSuccess: (linked, choice) => {
      if (linked) setBrowser(choice.conversationId, true);
    },
  });
  return (
    <div className="border-foreground/10 mt-4 border-t pt-4">
      <p className="text-muted-foreground mb-3 text-xs">{t("browserTitle")}</p>
      <div
        role="radiogroup"
        aria-label={t("browserTitle")}
        className="bg-foreground/4 grid grid-cols-2 gap-1 rounded-xl p-1"
      >
        <button
          type="button"
          role="radio"
          aria-checked={!local}
          disabled={selection.isPending}
          onClick={() => setBrowser(conversationId, false)}
          className={cn(
            "flex min-h-10 items-center justify-center gap-2 rounded-lg px-2 text-xs",
            !local && "bg-background shadow-sm",
          )}
        >
          <Globe className="size-4" aria-hidden />
          {t("agentBrowser")}
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={local}
          disabled={device === undefined || selection.isPending}
          onClick={() => selection.mutate({ conversationId, linked: device?.linked === true })}
          className={cn(
            "flex min-h-10 items-center justify-center gap-2 rounded-lg px-2 text-xs",
            local && "bg-background shadow-sm",
          )}
        >
          <Laptop className="size-4" aria-hidden />
          {t("computerBrowser")}
        </button>
      </div>
      <p className="text-muted-foreground mt-2 text-xs leading-relaxed">
        {t("browserIndependent")}
      </p>
      {local && device?.connected === false && (
        <p role="status" className="text-muted-foreground mt-2 text-xs">
          {t("offline")}
        </p>
      )}
    </div>
  );
}

function ComputerWorkOn() {
  const t = useTranslations("chat.controls.workOn");
  const modeHintId = useId();
  const { data: device } = useDeviceStatus();
  const { link } = useDeviceLink();
  const { state, pick, revoke } = useLocalFolders();
  const services = useLocalServices().state.data ?? [];
  const conversationId = useConversationStore((store) => store.currentConversationId);
  const target = useWorkOnStore((store) => store.targetFor(conversationId));
  const setTarget = useWorkOnStore((store) => store.set);
  const onComputer = target !== null;

  const linked = device?.linked === true;
  const grants = state.data?.grants ?? [];
  const modes = state.data?.modes ?? [];
  const selectedMode =
    target?.mode ?? (modes.includes("workspace_write") ? "workspace_write" : "read_only");

  // Mutation-level callbacks survive the popover unmounting while a native
  // dialog has focus. Per-call mutate callbacks are dropped on unmount.
  const selection = useMutation({
    mutationFn: async (choice: {
      mode: LocalMode;
      linked: boolean;
      conversationId: string | null;
      target: LocalTarget | null;
    }) => {
      if (!choice.linked) {
        const status = await link.mutateAsync();
        if (!status.linked) return null;
      }
      return pick.mutateAsync(choice.mode);
    },
    onSuccess: (grant, choice) => {
      if (grant)
        setTarget(choice.conversationId, {
          ...choice.target,
          folder: grant.path,
          mode: grant.mode,
        });
    },
  });
  const chooseFolder = (mode: LocalMode) =>
    selection.mutate({ mode, linked, conversationId, target });

  const chooseCloud = () => {
    setTarget(conversationId, null);
  };

  const chooseComputer = () => {
    if (onComputer) return;
    chooseFolder(selectedMode);
  };

  return (
    <div className="border-foreground/10 mt-4 border-t pt-4">
      <p className="text-muted-foreground mb-3 text-xs leading-relaxed">{t("title")}</p>
      <div
        role="radiogroup"
        aria-label={t("title")}
        className="bg-foreground/[0.04] grid grid-cols-2 gap-1 rounded-xl p-1"
      >
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
            disabled={
              link.isPending ||
              pick.isPending ||
              selection.isPending ||
              (key === "computer" && (device === undefined || modes.length === 0))
            }
            aria-busy={key === "computer" && link.isPending}
            onClick={onClick}
            className={cn(
              "focus-visible:ring-ring inline-flex min-h-9 min-w-0 items-center justify-center gap-2 rounded-lg px-2 py-2 text-xs font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none",
              active
                ? "bg-background text-foreground shadow-sm"
                : "text-foreground/70 hover:bg-foreground/[0.04]",
              "disabled:cursor-wait disabled:opacity-45",
            )}
          >
            <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
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
          <div className="border-foreground/10 space-y-3 border-t pt-3">
            <label className="block space-y-1.5">
              <span className="text-muted-foreground text-xs font-medium">{t("folderAccess")}</span>
              <span className="relative block">
                <select
                  value={selectedMode}
                  disabled={modes.length === 0 || pick.isPending}
                  onChange={(event) => {
                    const mode = modes.find((mode) => mode === event.target.value);
                    if (mode && mode !== target?.mode) chooseFolder(mode);
                  }}
                  className="border-foreground/12 bg-background text-foreground focus-visible:ring-ring h-9 w-full appearance-none rounded-lg border pr-8 pl-3 text-xs focus-visible:ring-2 focus-visible:outline-none disabled:opacity-50"
                  aria-describedby={modeHintId}
                >
                  {modes.map((mode) => (
                    <option key={mode} value={mode}>
                      {t(`mode.${mode}`)}
                    </option>
                  ))}
                </select>
                <ChevronDown
                  className="text-muted-foreground pointer-events-none absolute top-1/2 right-3 h-3.5 w-3.5 -translate-y-1/2"
                  aria-hidden
                />
              </span>
            </label>
            <p id={modeHintId} className="text-muted-foreground text-xs leading-relaxed">
              {t(`modeHint.${selectedMode}`)}
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={pick.isPending || modes.length === 0}
              onClick={() => chooseFolder(selectedMode)}
              className="w-full justify-center"
            >
              <FolderOpen aria-hidden />
              {t("pick")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
