"use client";

import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { cn } from "@/lib/utils";
import type { AssistantState } from "@/types/assistant";

interface AssistantLauncherProps {
  assistant: AssistantState;
  agentId: string;
  open: boolean;
  onToggle: () => void;
}

/** The round button with the assistant's face, in the corner of every page. */
export function AssistantLauncher({ assistant, agentId, open, onToggle }: AssistantLauncherProps) {
  const t = useTranslations("assistantWidget");
  return (
    <button
      type="button"
      aria-label={open ? t("close") : t("open", { name: assistant.name })}
      aria-expanded={open}
      onClick={onToggle}
      // Over a full-screen window on a phone it would cover the conversation, and
      // the window's own × closes it there.
      className={cn(
        "bg-background border-border fixed right-4 bottom-20 z-50 rounded-full border p-1 shadow-lg transition-transform hover:scale-105 md:right-6 md:bottom-6",
        open && "hidden md:block",
      )}
    >
      <AssistantFace assistant={assistant} agentId={agentId} size="lg" />
    </button>
  );
}

/** The assistant's avatar: its own picture, or the face drawn from its handle. */
export function AssistantFace({
  assistant,
  agentId,
  size,
}: {
  assistant: AssistantState;
  agentId: string;
  size: "sm" | "lg";
}) {
  return (
    <AgentAvatar
      agentId={agentId}
      slug={assistant.slug ?? ""}
      hasAvatar={assistant.avatar_url !== null}
      colorSlot={assistant.avatar_color}
      size={size}
    />
  );
}

/** Where the assistant's window sits: full screen on a phone, a panel above the button otherwise. */
export const WINDOW_CLASSES =
  "bg-background border-border fixed z-50 flex flex-col overflow-hidden shadow-2xl inset-0 md:inset-auto md:right-6 md:bottom-24 md:h-[min(640px,80vh)] md:w-[400px] md:rounded-2xl md:border";
