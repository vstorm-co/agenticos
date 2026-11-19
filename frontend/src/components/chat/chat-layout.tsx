"use client";

import { useState, type ReactNode } from "react";
import "./chat-layout.css";
import { Check, ChevronDown, SlidersHorizontal, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useSavedChatControls } from "@/hooks/use-saved-chat-controls";
import { useModelProviders, usePermissions } from "@/hooks";
import { useAgentSelectionStore } from "@/stores";
import { useAgents } from "@/hooks/use-agents";
import { usableForAgents } from "@/lib/model-profiles";
import { ModelIcon } from "@/components/icons/model-icon";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { PersonalCodingAccount } from "@/components/settings/coding-accounts";
import { Perm } from "@/types/permissions";
import { ChatModelPicker } from "./chat-model-picker";
import { PersonalModelConnection } from "./personal-model-connection";
import { ConversationNotifications, WorkOn } from "./work-on";
import { YourConnections } from "./your-connections";
import { RememberedApprovals } from "./remembered-approvals";

import { MainChatContext } from "./main-chat-context";

/** The main chat composition; embedded agent and Architect chats stay independent. */
export function ChatLayout({ children }: { children: ReactNode }) {
  return (
    <MainChatContext.Provider value={true}>
      <div className="chat-layout relative flex h-full min-h-0 flex-1 flex-col" data-chat-layout>
        <div className="chat-layout-content min-h-0 flex-1">{children}</div>
      </div>
    </MainChatContext.Provider>
  );
}

function ComposerModelControl({ onChange }: { onChange?: (id: string | null) => void }) {
  const t = useTranslations("chat.controls");
  const common = useTranslations("common");
  const modelCopy = useTranslations("chat.modelPicker");
  const { can } = usePermissions();
  const selectedAgentId = useAgentSelectionStore((state) => state.selectedAgentId);
  const { agents } = useAgents();
  const agent = agents.find((entry) => entry.id === selectedAgentId);
  const { profiles } = useModelProviders();
  const { modelProfileId, update } = useSavedChatControls();
  const model =
    modelProfileId === null
      ? (agent?.published_model ?? null)
      : (profiles.find((entry) => entry.id === modelProfileId) ?? null);
  const [open, setOpen] = useState(false);
  const change = (id: string | null) => {
    update({ modelProfileId: id });
    onChange?.(id);
  };
  const caption = model?.model.split("/").at(-1) || t("modelSection");
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={t("modelSection")}
          data-chat-model
          title={model?.label ?? t("modelSection")}
          className="group/model focus-visible:ring-ring hover:bg-muted inline-flex h-9 max-w-52 min-w-0 items-center gap-2 rounded-full px-2.5 text-xs outline-none focus-visible:ring-2"
        >
          {model && <ModelIcon model={model.model} provider={model.provider} />}
          <span className="truncate">{caption}</span>
          <ChevronDown
            className="text-muted-foreground size-3 shrink-0 transition-transform duration-150 group-data-[state=open]/model:rotate-180 motion-reduce:transition-none"
            aria-hidden
          />
        </button>
      </PopoverTrigger>
      <PopoverContent
        data-chat-popover
        aria-label={t("modelSection")}
        side="top"
        align="end"
        className="max-h-[min(520px,var(--radix-popover-content-available-height))] w-[min(360px,calc(100vw-1.5rem))] overflow-y-auto rounded-xl p-3"
      >
        <div className="mb-2 flex items-center justify-between text-xs font-medium">
          {t("modelSection")}
          <button
            type="button"
            aria-label={common("close")}
            onClick={() => setOpen(false)}
            className="hover:bg-muted grid size-7 place-items-center rounded-md"
          >
            <X className="size-3.5" aria-hidden />
          </button>
        </div>
        {agent?.personal_model_key ? (
          <PersonalModelConnection agentId={selectedAgentId} manage />
        ) : (
          <div className="space-y-2">
            {can(Perm.connectionsManage) && (
              <div className="space-y-1">
                {agent?.published_model && (
                  <button
                    type="button"
                    aria-pressed={modelProfileId === null}
                    className="hover:bg-muted flex min-h-10 w-full items-center gap-2 rounded-xl px-2 text-left text-xs"
                    onClick={() => {
                      change(null);
                      setOpen(false);
                    }}
                  >
                    <ModelIcon
                      model={agent.published_model.model}
                      provider={agent.published_model.provider}
                    />
                    <span className="min-w-0 flex-1 truncate">
                      {agent.published_model.model.split("/").at(-1)}
                    </span>
                    <span className="text-muted-foreground text-[10px]">
                      {modelCopy("agentModel")}
                    </span>
                    {modelProfileId === null && <Check className="size-3.5" aria-hidden />}
                  </button>
                )}
                {profiles
                  .filter(
                    (profile) =>
                      usableForAgents(profile) && profile.id !== agent?.published_model?.profile_id,
                  )
                  .map((profile) => (
                    <button
                      key={profile.id}
                      type="button"
                      aria-pressed={modelProfileId === profile.id}
                      className="hover:bg-muted flex min-h-10 w-full items-center gap-2 rounded-xl px-2 text-left text-xs"
                      onClick={() => {
                        change(profile.id);
                        setOpen(false);
                      }}
                    >
                      <ModelIcon model={profile.model} provider={profile.provider} />
                      <span className="min-w-0 flex-1 truncate">{profile.label}</span>
                      {modelProfileId === profile.id && <Check className="size-3.5" aria-hidden />}
                    </button>
                  ))}
              </div>
            )}
            <details className="border-border border-t pt-2">
              <summary className="text-muted-foreground cursor-pointer py-1 text-xs">
                {modelCopy("changeModel")}
              </summary>
              <div className="pt-3">
                <ChatModelPicker
                  compact
                  value={modelProfileId}
                  agentModel={agent?.published_model ?? null}
                  onChange={change}
                />
              </div>
            </details>
          </div>
        )}
        {modelProfileId !== null && (
          <button
            type="button"
            className="text-muted-foreground mt-3 text-xs hover:underline"
            onClick={() => change(null)}
          >
            {t("backAgentAposS")}
          </button>
        )}
      </PopoverContent>
    </Popover>
  );
}

/** Keep connection management; standing permissions already have Agent rules. */
export function ChatComposerControls({
  usageSlot,
  desktop,
  harnesses,
  agentCapabilities,
  onModelProfileChange,
  settingsOnly = false,
}: {
  usageSlot?: ReactNode;
  desktop: boolean;
  harnesses: readonly ("claude_code" | "codex")[];
  agentCapabilities?: readonly string[] | null;
  onModelProfileChange?: (id: string | null) => void;
  settingsOnly?: boolean;
}) {
  const t = useTranslations("chat.controls");
  const chat = useTranslations("chat");
  const common = useTranslations("common");
  const { can } = usePermissions();
  const [open, setOpen] = useState(false);
  return (
    <div
      className="chat-composer-controls flex min-w-0 items-center gap-1"
      data-chat-location={settingsOnly ? "settings" : "model"}
    >
      {!settingsOnly && usageSlot && <div data-chat-usage>{usageSlot}</div>}
      {!settingsOnly && <ComposerModelControl onChange={onModelProfileChange} />}
      {settingsOnly && (
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <button
              type="button"
              aria-label={t("label")}
              title={t("label")}
              data-chat-settings
              data-chat-settings-trigger
              data-tour="chat-settings"
              className="focus-visible:ring-ring text-muted-foreground hover:bg-muted grid size-9 shrink-0 place-items-center rounded-lg outline-none focus-visible:ring-2"
            >
              <SlidersHorizontal className="size-4" aria-hidden />
            </button>
          </PopoverTrigger>
          <PopoverContent
            onInteractOutside={(event) => {
              if (
                document.querySelector(".driver-popover") ||
                (event.target instanceof Element &&
                  event.target.closest("[data-coding-account-connect]"))
              )
                event.preventDefault();
            }}
            aria-label={t("label")}
            side="top"
            align="end"
            className="max-h-[min(460px,var(--radix-popover-content-available-height))] w-[min(340px,calc(100vw-1.5rem))] overflow-y-auto rounded-xl p-3"
          >
            <div className="mb-3 flex items-center justify-between text-sm font-medium">
              {t("label")}
              <button
                type="button"
                aria-label={common("close")}
                onClick={() => setOpen(false)}
                className="hover:bg-muted grid size-7 place-items-center rounded-md"
              >
                <X className="size-3.5" aria-hidden />
              </button>
            </div>
            <div className="space-y-3 text-xs">
              <YourConnections />
              {(desktop || harnesses.length > 0) && (
                <details className="rounded-lg border p-2.5">
                  <summary className="cursor-pointer font-medium">{t("toolsTab")}</summary>
                  <div className="mt-3 space-y-3">
                    {harnesses.map((harness) => (
                      <PersonalCodingAccount key={harness} harness={harness} />
                    ))}
                    {desktop && <WorkOn agentCapabilities={agentCapabilities} />}
                  </div>
                </details>
              )}
              <ConversationNotifications />
              {can(Perm.approvalsDecide) && (
                <details className="rounded-lg border p-2.5">
                  <summary className="cursor-pointer font-medium">
                    {chat("approvalRememberedTitle")}
                  </summary>
                  <div className="mt-3">
                    <RememberedApprovals />
                  </div>
                </details>
              )}
            </div>
          </PopoverContent>
        </Popover>
      )}
    </div>
  );
}
