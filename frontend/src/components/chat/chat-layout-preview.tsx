"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import { ChevronDown, SlidersHorizontal, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useSavedChatControls } from "@/hooks/use-saved-chat-controls";
import { useModelProviders, usePermissions } from "@/hooks";
import { useAgentSelectionStore } from "@/stores";
import { useAgents } from "@/hooks/use-agents";
import { ModelIcon } from "@/components/icons/model-icon";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { PersonalCodingAccount } from "@/components/settings/coding-accounts";
import { Perm } from "@/types/permissions";
import { ChatModelPicker } from "./chat-model-picker";
import { PersonalModelConnection } from "./personal-model-connection";
import { ConversationNotifications, WorkOn } from "./work-on";
import { YourConnections } from "./your-connections";
import { RememberedApprovals } from "./remembered-approvals";

export type ChatLayoutVariant = "composer" | "header" | "floating";
const PreviewContext = createContext<ChatLayoutVariant | null>(null);
export const useChatLayoutPreview = () => useContext(PreviewContext);

/** Review-only alternatives; the regular chat stays unchanged until one is chosen. */
export function ChatLayoutPreview({
  variant,
  children,
}: {
  variant: string | null;
  children: ReactNode;
}) {
  const layout =
    process.env.NODE_ENV === "development" &&
    (variant === "composer" || variant === "header" || variant === "floating")
      ? variant
      : null;
  if (layout === null) return children;
  return (
    <PreviewContext.Provider value={layout}>
      <div className="relative flex h-full min-h-0 flex-1 flex-col" data-chat-layout={layout}>
        {layout === "header" && (
          <div className="border-border flex h-12 shrink-0 items-center justify-end border-b px-4">
            <PreviewModelControl />
          </div>
        )}
        {layout === "floating" && (
          <div className="bg-background/95 ring-border/60 absolute top-16 right-4 z-20 rounded-full shadow-sm ring-1 md:top-4">
            <PreviewModelControl />
          </div>
        )}
        {children}
      </div>
    </PreviewContext.Provider>
  );
}

function PreviewModelControl({ onChange }: { onChange?: (id: string | null) => void }) {
  const t = useTranslations("chat.controls");
  const common = useTranslations("common");
  const selectedAgentId = useAgentSelectionStore((state) => state.selectedAgentId);
  const { agents } = useAgents();
  const agent = agents.find((entry) => entry.id === selectedAgentId);
  const { profiles } = useModelProviders();
  const { modelProfileId, update } = useSavedChatControls();
  const model =
    profiles.find((entry) => entry.id === modelProfileId) ?? agent?.published_model ?? null;
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
          title={model?.label ?? t("modelSection")}
          className="focus-visible:ring-ring hover:bg-muted inline-flex h-9 max-w-52 min-w-0 items-center gap-2 rounded-full px-2.5 text-xs outline-none focus-visible:ring-2"
        >
          {model && <ModelIcon model={model.model} provider={model.provider} />}
          <span className="truncate">{caption}</span>
          <ChevronDown className="text-muted-foreground size-3 shrink-0" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent
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
          <ChatModelPicker
            compact
            value={modelProfileId}
            agentModel={agent?.published_model ?? null}
            onChange={change}
          />
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
export function PreviewChatControls({
  usageSlot,
  desktop,
  harnesses,
  agentCapabilities,
  onModelProfileChange,
}: {
  usageSlot?: ReactNode;
  desktop: boolean;
  harnesses: readonly ("claude_code" | "codex")[];
  agentCapabilities?: readonly string[] | null;
  onModelProfileChange?: (id: string | null) => void;
}) {
  const layout = useChatLayoutPreview();
  const t = useTranslations("chat.controls");
  const chat = useTranslations("chat");
  const common = useTranslations("common");
  const { can } = usePermissions();
  const [open, setOpen] = useState(false);
  return (
    <div className="flex min-w-0 items-center gap-1">
      {layout === "composer" && <PreviewModelControl onChange={onModelProfileChange} />}
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            aria-label={t("label")}
            title={t("label")}
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
            {usageSlot && <div className="border-t pt-3">{usageSlot}</div>}
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
