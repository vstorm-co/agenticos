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
  /** Tucked into the screen's right edge, with only a sliver showing. */
  docked?: boolean;
  /** Something is waiting for the reader while the button is tucked away. */
  waiting?: boolean;
  /** The pointer reached the button - the reader is still about. */
  onHover?: () => void;
  /**
   * Whether the page has a composer along the bottom. The corner the button
   * sits in is that composer's send controls on any screen, so it steps out
   * there; the chat's own agent picker reaches the assistant.
   */
  overComposer?: boolean;
}

/** In the phone header; at the desktop edge where no top bar exists. */
export function AssistantLauncher({
  assistant,
  agentId,
  open,
  docked = false,
  waiting = false,
  onToggle,
  onHover,
  overComposer = false,
}: AssistantLauncherProps) {
  const t = useTranslations("assistantWidget");
  return (
    <button
      type="button"
      aria-label={
        open ? t("close") : t("open", { name: architectName(assistant, t("defaultName")) })
      }
      aria-expanded={open}
      data-docked={docked || undefined}
      onClick={onToggle}
      onPointerEnter={onHover}
      // Gone while the window is open, on every screen: the window takes its
      // corner, and the window's own × closes it. Docked, it slides into the
      // right edge and leaves a sliver to pull it back out by; a pointer over
      // the sliver shows the whole face again.
      className={cn(
        "bg-background border-border fixed top-0.5 right-14 z-40 rounded-full p-1 transition-transform duration-300 ease-out hover:scale-105 active:scale-95 md:top-auto md:right-6 md:bottom-6 md:z-50 md:border md:shadow-lg [html[data-typing]_&]:hidden",
        docked &&
          "md:right-0 md:translate-x-[calc(100%-1.125rem)] md:rounded-r-none md:border-r-0 md:hover:translate-x-0 md:hover:scale-100 md:focus-visible:translate-x-0",
        open && "hidden",
        overComposer && "hidden",
      )}
    >
      <span className="block size-9 md:size-14 [&>*]:size-full">
        <AssistantFace assistant={assistant} agentId={agentId} size="lg" />
      </span>
      {waiting && (
        <span
          aria-hidden
          className="bg-destructive ring-background absolute top-1 left-1 h-2.5 w-2.5 rounded-full ring-2"
        />
      )}
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

/**
 * What the console calls the assistant: "Architect" in the reader's language,
 * until an administrator names it something else - then that name, as written.
 */
export function architectName(
  assistant: Pick<AssistantState, "name" | "named_by_default">,
  defaultName: string,
): string {
  return assistant.named_by_default ? defaultName : assistant.name;
}

/** Where the assistant's window sits: full screen on a phone, a panel above the button otherwise. */
export const WINDOW_CLASSES =
  "bg-background border-border fixed z-50 flex flex-col overflow-hidden shadow-2xl inset-0 pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)] md:inset-auto md:pt-0 md:pb-0 md:right-6 md:bottom-6 md:h-[min(720px,calc(100vh-3rem))] md:w-[min(520px,calc(100vw-3rem))] md:rounded-2xl md:border";

/**
 * The widget's root: usable above an open dialog, without closing it.
 *
 * A modal dialog turns pointer events off on the page and closes on a press
 * outside itself - which is everything the widget is. The Architect is most
 * useful exactly when somebody is stuck in a form, so the widget takes pointer
 * events back and keeps its presses from reaching the document, where the
 * dialog listens for them.
 *
 * Stopped in React's own handler, once the widget's controls have had the
 * press: a native listener on this div stopped it before React - which listens
 * at its root - ever saw it, so every control opening on `pointerdown`, the
 * composer's `+` menu among them, was dead here. `stopImmediatePropagation`
 * because that root may be the document itself, where the dialog listens too,
 * later.
 */
export function WidgetRoot({ children }: { children: React.ReactNode }) {
  return (
    // The Builder's test panel takes the corner the widget sits in, and is a chat
    // of its own; the Architect comes back when it closes.
    <div
      data-tour="assistant-widget"
      className="pointer-events-auto [html[data-test-panel]_&]:hidden"
      onPointerDown={(event) => event.nativeEvent.stopImmediatePropagation()}
    >
      {children}
    </div>
  );
}
