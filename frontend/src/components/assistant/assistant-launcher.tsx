"use client";

import { useEffect, useRef } from "react";
import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { cn } from "@/lib/utils";
import type { AssistantState } from "@/types/assistant";

interface AssistantLauncherProps {
  assistant: AssistantState;
  agentId: string;
  open: boolean;
  onToggle: () => void;
  /**
   * Whether the page has a composer along the bottom. On a phone the corner the
   * button sits in is that composer's send controls, so it steps out there; the
   * chat's own agent picker reaches the assistant.
   */
  overComposer?: boolean;
}

/** The round button with the assistant's face, in the corner of every page. */
export function AssistantLauncher({
  assistant,
  agentId,
  open,
  onToggle,
  overComposer = false,
}: AssistantLauncherProps) {
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
        "bg-background border-border fixed right-4 bottom-[calc(5rem+env(safe-area-inset-bottom))] z-50 rounded-full border p-1 shadow-lg transition-transform hover:scale-105 active:scale-95 md:right-6 md:bottom-6 [html[data-typing]_&]:hidden",
        open && "hidden md:block",
        overComposer && "max-md:hidden",
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
  "bg-background border-border fixed z-50 flex flex-col overflow-hidden shadow-2xl inset-0 pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)] md:inset-auto md:pt-0 md:pb-0 md:right-6 md:bottom-24 md:h-[min(640px,80vh)] md:w-[400px] md:rounded-2xl md:border";

/**
 * The widget's root: usable above an open dialog, without closing it.
 *
 * A modal dialog turns pointer events off on the page and closes on a press
 * outside itself - which is everything the widget is. The Architect is most
 * useful exactly when somebody is stuck in a form, so the widget takes pointer
 * events back and keeps its presses from reaching the document, where the
 * dialog listens for them.
 */
export function WidgetRoot({ children }: { children: React.ReactNode }) {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // Set by the time an effect runs: the div is this component's only output.
    const element = root.current;
    const keep = (event: PointerEvent) => event.stopPropagation();
    element?.addEventListener("pointerdown", keep);
    return () => element?.removeEventListener("pointerdown", keep);
  }, []);
  return (
    // The Builder's test panel takes the corner the widget sits in, and is a chat
    // of its own; the Architect comes back when it closes.
    <div
      ref={root}
      data-tour="assistant-widget"
      className="pointer-events-auto [html[data-test-panel]_&]:hidden"
    >
      {children}
    </div>
  );
}
