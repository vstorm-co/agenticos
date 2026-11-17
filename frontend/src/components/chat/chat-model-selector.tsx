"use client";

import { useState } from "react";
import { AlertCircle, Check, ChevronDown, Settings2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ProviderIcon } from "@/components/vault/provider-icon";
import { useModelProviders } from "@/hooks/use-model-providers";
import { usePermissions } from "@/hooks/use-permissions";
import { useSavedChatControls } from "@/hooks/use-saved-chat-controls";
import { modelShortName, usableForAgents } from "@/lib/model-profiles";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";
import type { PublishedModel } from "@/types/agents";
import { Perm } from "@/types/permissions";
import { ChatModelMenu } from "./chat-model-menu";

interface Props {
  agentModel: PublishedModel | null;
  readOnly: boolean;
  isProcessing: boolean;
  canEditAgent: boolean;
  onChange: (profileId: string | null) => void;
}

/** A saved chat preference, never a write to the agent or its published spec. */
export function ChatModelSelector({
  agentModel,
  readOnly,
  isProcessing,
  canEditAgent,
  onChange,
}: Props) {
  const t = useTranslations("chat.modelSelector");
  const tm = useTranslations("chat.modelPicker");
  const tc = useTranslations("common");
  const [open, setOpen] = useState(false);
  const [pendingModelChange, setPendingModelChange] = useState(false);
  const { can } = usePermissions();
  const { modelProfileId, update } = useSavedChatControls();
  const { profiles, catalog, profilesStatus, refetchProfiles } = useModelProviders();

  const profile = profiles.find((item) => item.id === (modelProfileId ?? agentModel?.profile_id));
  const current = modelProfileId === null ? agentModel : profile;
  const unavailable =
    (profile !== undefined && !usableForAgents(profile)) ||
    (modelProfileId !== null && profilesStatus === "loaded" && profile === undefined);
  const label = current
    ? modelShortName(current.label)
    : modelProfileId !== null
      ? profilesStatus === "pending"
        ? tc("loading")
        : t("unavailable")
      : tm("agentModel");
  const mayChoose = !readOnly && can(Perm.connectionsManage);
  const mayOpenSettings = !readOnly && canEditAgent;
  const summary = (
    <>
      {current && <ProviderIcon provider={current.provider} className="size-4 shrink-0" />}
      <span className="min-w-0 truncate">{label}</span>
      {unavailable && (
        <AlertCircle aria-label={t("unavailable")} className="text-destructive size-3.5 shrink-0" />
      )}
      <span className="text-muted-foreground hidden text-[10px] sm:inline">
        {modelProfileId === null ? t("default") : t("override")}
      </span>
      {isProcessing && pendingModelChange && (
        <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-800 dark:text-amber-300">
          {t("afterTurnBadge")}
        </span>
      )}
    </>
  );
  const choose = (id: string | null) => {
    if (isProcessing && id !== modelProfileId) setPendingModelChange(true);
    update({ modelProfileId: id });
    onChange(id);
    setOpen(false);
  };
  const openSettings = () => {
    setOpen(false);
    useBrowserPanelStore.getState().openSurface("settings");
  };
  if (!mayChoose) {
    return (
      <div className="flex min-w-0 items-center gap-2">
        <span
          className="bg-foreground/5 inline-flex max-w-64 min-w-0 items-center gap-2 rounded-full px-3 py-2 text-xs"
          title={readOnly ? label : tm("needsConnectionsManage")}
        >
          {summary}
        </span>
        {mayOpenSettings && (
          <button
            type="button"
            aria-label={t("editReasoning")}
            title={t("editReasoning")}
            onClick={openSettings}
            className="text-muted-foreground hover:text-foreground hover:bg-foreground/5 inline-flex size-9 shrink-0 items-center justify-center rounded-full transition-colors"
          >
            <Settings2 aria-hidden className="size-4" />
          </button>
        )}
      </div>
    );
  }
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-tour="chat-model-selector"
          aria-label={t(unavailable ? "chooseUnavailable" : "choose", { model: label })}
          title={current?.label ?? label}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setOpen(true);
            }
          }}
          className="bg-foreground/5 hover:bg-foreground/10 touch:min-h-11 inline-flex max-w-64 min-w-0 items-center gap-2 rounded-full px-3 py-2 text-xs font-medium transition-colors"
        >
          {summary}
          <ChevronDown aria-hidden className="text-muted-foreground size-3.5 shrink-0" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        side="bottom"
        sideOffset={8}
        aria-label={t("title")}
        className="bg-popover max-h-[var(--radix-popover-content-available-height)] w-[440px] max-w-[calc(100vw-2rem)] overflow-y-auto rounded-xl p-0"
      >
        <div className="space-y-2 border-b p-3">
          <p className="text-muted-foreground text-xs">
            {isProcessing ? t("afterTurn") : t("scope")}
          </p>
          <button
            type="button"
            aria-pressed={modelProfileId === null}
            onClick={() => choose(null)}
            className="hover:bg-accent flex w-full items-center justify-between gap-2 rounded-lg px-2 py-2 text-left text-xs"
          >
            {modelProfileId === null && <Check aria-hidden className="size-3.5 shrink-0" />}
            <span className="flex-1">{t("useDefault")}</span>
            <span className="text-muted-foreground truncate">
              {agentModel?.label ?? tm("agentModel")}
            </span>
          </button>
        </div>
        {profilesStatus === "failed" ? (
          <div role="alert" className="space-y-2 p-4 text-xs">
            <p>{tm("profilesUnavailable")}</p>
            <button type="button" className="underline" onClick={() => void refetchProfiles()}>
              {tc("retry")}
            </button>
          </div>
        ) : profilesStatus === "pending" ? (
          <p role="status" className="text-muted-foreground p-4 text-xs">
            {tc("loading")}
          </p>
        ) : (
          <ChatModelMenu
            profiles={profiles}
            catalog={catalog}
            value={modelProfileId}
            currentProvider={current?.provider}
            onChange={choose}
          />
        )}
        {mayOpenSettings && (
          <div className="border-t p-2">
            <button
              type="button"
              onClick={openSettings}
              className="hover:bg-accent flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-xs"
            >
              <Settings2 aria-hidden className="text-muted-foreground size-3.5 shrink-0" />
              {t("editReasoning")}
            </button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
