"use client";

import { NativeDisclosure } from "@/components/ui/native-disclosure";

import { useId, useState, type ReactNode } from "react";
import "./chat-layout.css";
import {
  ChevronDown,
  SlidersHorizontal,
  ShieldCheck,
  SquareTerminal,
  RotateCcw,
  X,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useSavedChatControls } from "@/hooks/use-saved-chat-controls";
import { useModelProviders, usePermissions, useProviderModels } from "@/hooks";
import { useAgentSelectionStore } from "@/stores";
import { useAgents } from "@/hooks/use-agents";
import { useSubscriptionAccounts } from "@/hooks/use-subscription-accounts";
import { ModelIcon } from "@/components/icons/model-icon";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { PersonalCodingAccount } from "@/components/settings/coding-accounts";
import { Perm } from "@/types/permissions";
import { catalogModelName } from "@/lib/model-profiles";
import { cn } from "@/lib/utils";
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
  const selectedAgentId = useAgentSelectionStore((state) => state.selectedAgentId);
  const { agents } = useAgents();
  const agent = agents.find((entry) => entry.id === selectedAgentId);
  const { profiles, catalog } = useModelProviders();
  const { can, isLoading: permissionsLoading } = usePermissions();
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
  const captionId = useId();
  const sources = useTranslations("modelSources");
  const subscriptions = useSubscriptionAccounts({
    enabled: model?.provider === "subscription_accounts",
  });
  const account = subscriptions.accounts.data?.items.find(
    (entry) => entry.model_prefix && model?.model.startsWith(`${entry.model_prefix}/`),
  );
  const identity =
    model?.provider === "subscription_accounts"
      ? account?.email || account?.label || sources("subscriptions")
      : catalog.find((entry) => entry.id === model?.provider)?.name;
  const { models } = useProviderModels(model && can(Perm.agentsView) ? model.provider : "");
  const caption = model
    ? catalogModelName(
        model.model,
        models.find((entry) => entry.id === model.model)?.name ?? model.model.split("/").at(-1),
      )
    : t("modelSection");
  const library = !agent?.personal_model_key && (permissionsLoading || can(Perm.connectionsManage));
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={t("modelSection")}
          aria-describedby={model ? captionId : undefined}
          data-chat-model
          title={[caption, identity].filter(Boolean).join(" · ")}
          className="group/model focus-visible:ring-ring hover:bg-muted inline-flex min-h-11 min-w-0 items-center gap-2 rounded-lg px-2.5 text-sm outline-none focus-visible:ring-2"
        >
          {model && <ModelIcon model={model.model} provider={model.provider} />}
          <span id={captionId} className="chat-model-caption">
            <span className="chat-model-name">{caption}</span>{" "}
            {identity && <span className="chat-model-identity">{identity}</span>}
          </span>
          <ChevronDown
            className="text-muted-foreground size-3 shrink-0 transition-transform duration-150 group-data-[state=open]/model:rotate-180 motion-reduce:transition-none"
            aria-hidden
          />
        </button>
      </PopoverTrigger>
      <PopoverContent
        data-chat-popover
        onEscapeKeyDown={(event) => {
          if (event.target instanceof Element && event.target.closest("[data-model-search]"))
            event.preventDefault();
        }}
        onInteractOutside={(event) => {
          if (event.target instanceof Element && event.target.closest('[role="dialog"]'))
            event.preventDefault();
        }}
        aria-label={t("modelSection")}
        side="top"
        align="end"
        className={cn(
          "max-h-[min(600px,var(--radix-popover-content-available-height))] w-[min(640px,calc(100vw-1.5rem))] overflow-y-auto rounded-2xl p-0",
          // Keep the anchor stable while permissions and the catalog settle.
          library &&
            "flex h-[min(29rem,var(--radix-popover-content-available-height,29rem))] min-h-0 flex-col overflow-clip",
        )}
      >
        <div className="border-border bg-popover sticky top-0 z-10 flex shrink-0 items-center justify-between gap-2 border-b px-4 py-2 text-xs font-medium">
          {t("modelSection")}
          <div className="ml-auto flex min-w-0 items-center gap-1">
            {modelProfileId !== null && agent?.published_model && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="min-w-0 text-xs"
                onClick={() => {
                  change(null);
                  setOpen(false);
                }}
              >
                <RotateCcw aria-hidden className="size-3.5 shrink-0" />
                <span className="truncate">{t("backAgentAposS")}</span>
              </Button>
            )}
            <button
              type="button"
              aria-label={common("close")}
              onClick={() => setOpen(false)}
              className="hover:bg-muted grid size-7 place-items-center rounded-md"
            >
              <X className="size-3.5" aria-hidden />
            </button>
          </div>
        </div>
        {agent?.personal_model_key ? (
          <PersonalModelConnection agentId={selectedAgentId} manage />
        ) : permissionsLoading ? (
          <div aria-busy="true" className="grid gap-3 p-4">
            <Skeleton className="h-8 w-1/3" />
            <Skeleton className="h-36 w-full" />
          </div>
        ) : (
          <ChatModelPicker
            compact
            presentation="library"
            value={modelProfileId}
            agentModel={agent?.published_model ?? null}
            onChange={(id) => {
              change(id);
              setOpen(false);
            }}
          />
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
  const coding = useTranslations("codingAccounts");
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
            data-chat-settings-panel
            aria-label={t("label")}
            side="top"
            align="end"
            className="max-h-[min(520px,var(--radix-popover-content-available-height))] w-[min(360px,calc(100vw-1.5rem))] overflow-y-auto rounded-2xl p-0"
          >
            <div className="chat-settings-heading">
              <span className="inline-flex items-center gap-2">
                <SlidersHorizontal className="size-3.5" aria-hidden />
                {t("label")}
              </span>
              <button
                type="button"
                aria-label={common("close")}
                onClick={() => setOpen(false)}
                className="hover:bg-muted grid size-7 place-items-center rounded-md"
              >
                <X className="size-3.5" aria-hidden />
              </button>
            </div>
            <div className="chat-settings-body">
              <YourConnections />
              {(desktop || harnesses.length > 0) && (
                <NativeDisclosure className="chat-settings-section" open>
                  <summary>
                    <SquareTerminal className="size-4" aria-hidden />
                    <span>{t("toolsTab")}</span>
                    <ChevronDown className="chat-settings-chevron size-3.5" aria-hidden />
                  </summary>
                  <div className="chat-settings-section-body">
                    {harnesses.length > 0 && (
                      <p className="text-muted-foreground mb-1 text-xs leading-relaxed">
                        {coding("chatHelp")}
                      </p>
                    )}
                    {harnesses.map((harness) => (
                      <PersonalCodingAccount compact key={harness} harness={harness} />
                    ))}
                    {desktop && <WorkOn agentCapabilities={agentCapabilities} />}
                  </div>
                </NativeDisclosure>
              )}
              <ConversationNotifications />
              {can(Perm.approvalsDecide) && (
                <NativeDisclosure className="chat-settings-section">
                  <summary>
                    <ShieldCheck className="size-4" aria-hidden />
                    <span>{chat("approvalRememberedTitle")}</span>
                    <ChevronDown className="chat-settings-chevron size-3.5" aria-hidden />
                  </summary>
                  <div className="chat-settings-section-body">
                    <RememberedApprovals showTitle={false} />
                  </div>
                </NativeDisclosure>
              )}
            </div>
            <p className="chat-settings-footer">{t("savedAutomatically")}</p>
          </PopoverContent>
        </Popover>
      )}
    </div>
  );
}
