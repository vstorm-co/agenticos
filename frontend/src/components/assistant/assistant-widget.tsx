"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BellOff, History, MessageSquarePlus, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { usePathname } from "next/navigation";

import { useAgents, useApprovals, usePermissions } from "@/hooks";
import { useAssistant } from "@/hooks/use-assistant";
import { ASSISTANT_FRAME_PATH } from "@/lib/assistant-frame";
import { ASK, CONTEXT, HISTORY, NEW, type ToFrame } from "@/lib/assistant-messages";
import { bubbleFor, pageOf, readPreferences, setBubblesOff } from "@/lib/assistant-bubbles";
import { cn } from "@/lib/utils";
import { defaultLocale } from "@/i18n";
import { Perm } from "@/types/permissions";
import type { AssistantState } from "@/types/assistant";

import { AssistantBubble } from "./assistant-bubble";
import { AssistantFace, AssistantLauncher, WINDOW_CLASSES } from "./assistant-launcher";
import { AssistantSetup } from "./assistant-setup";

/** How long a page is looked at before the bubble speaks. */
const BUBBLE_DELAY_MS = 3000;

/** Counts page views across the widget's life, for the occasional tip. */
let visits = 0;

/**
 * The AI Architect in the corner of every console page (#2063).
 *
 * A round button with the assistant's face, a speech bubble above it that speaks
 * to the page and to what is waiting, and a window holding the conversation.
 * Shown only to somebody who may run agents - the assistant is an agent like any
 * other. Before it has a model it walks through connecting one instead.
 */
export function AssistantWidget() {
  const { assistant } = useAssistant();
  if (!assistant || !assistant.can_use || assistant.agent_id === null) return null;
  if (assistant.status === "ready") {
    return <ReadyWidget assistant={assistant} agentId={assistant.agent_id} />;
  }
  if (assistant.status === "needs_model") {
    return <AssistantSetup assistant={assistant} agentId={assistant.agent_id} />;
  }
  return null;
}

function ReadyWidget({ assistant, agentId }: { assistant: AssistantState; agentId: string }) {
  const t = useTranslations("assistantWidget");
  const locale = useLocale();
  const pathname = usePathname();
  const { can } = usePermissions();
  const { agents, isLoading: agentsLoading } = useAgents();
  const { total: pendingApprovals } = useApprovals({ enabled: can(Perm.approvalsDecide) });
  const [open, setOpen] = useState(false);
  const [everOpened, setEverOpened] = useState(false);
  // The page the bubble has waited out its moment on; on any other it is quiet.
  const [readyOn, setReadyOn] = useState<string | null>(null);
  const [preferences, setPreferences] = useState(readPreferences);
  const frame = useRef<HTMLIFrameElement>(null);
  const loaded = useRef(false);
  const queued = useRef<ToFrame[]>([]);

  const post = useCallback((message: ToFrame) => {
    const target = frame.current?.contentWindow;
    if (loaded.current && target) target.postMessage(message, window.location.origin);
    else queued.current.push(message);
  }, []);

  const context = useCallback(
    (): ToFrame => ({ type: CONTEXT, path: pageOf(pathname), title: document.title }),
    [pathname],
  );

  // A new page: tell the frame where the reader is, and give the bubble a moment.
  useEffect(() => {
    visits += 1;
    post(context());
    const timer = setTimeout(() => setReadyOn(pathname), BUBBLE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [context, post, pathname]);

  // Whatever was sent before the frame could hear it goes once it can, after
  // the page it opened on.
  useEffect(() => {
    const element = frame.current;
    if (!element) return;
    const onLoad = () => {
      loaded.current = true;
      const pending = [context(), ...queued.current];
      queued.current = [];
      for (const message of pending) post(message);
    };
    element.addEventListener("load", onLoad);
    return () => element.removeEventListener("load", onLoad);
  }, [everOpened, context, post]);

  const bubble = bubbleFor(
    pathname,
    { pendingApprovals, noAgents: !agentsLoading && agents.length === 0 },
    visits,
  );
  const speaking =
    readyOn === pathname &&
    !open &&
    bubble !== null &&
    !preferences.off &&
    !preferences.silenced.includes(pageOf(pathname));

  const openWindow = () => {
    setOpen(true);
    setEverOpened(true);
  };

  const ask = (text: string) => {
    openWindow();
    post({ type: ASK, text });
  };

  const prefix = locale === defaultLocale ? "" : `/${locale}`;

  return (
    <div data-tour="assistant-widget">
      {everOpened && (
        <div
          role="dialog"
          aria-label={assistant.name}
          className={cn(WINDOW_CLASSES, !open && "hidden")}
        >
          <header className="border-border flex items-center gap-2 border-b px-3 py-2">
            <AssistantFace assistant={assistant} agentId={agentId} size="sm" />
            <p className="min-w-0 flex-1 truncate text-sm font-semibold">{assistant.name}</p>
            <HeaderButton label={t("history")} onClick={() => post({ type: HISTORY })}>
              <History className="h-4 w-4" />
            </HeaderButton>
            <HeaderButton label={t("newConversation")} onClick={() => post({ type: NEW })}>
              <MessageSquarePlus className="h-4 w-4" />
            </HeaderButton>
            <HeaderButton
              label={preferences.off ? t("tipsOn") : t("tipsOff")}
              pressed={preferences.off}
              onClick={() => {
                setBubblesOff(!preferences.off);
                setPreferences(readPreferences());
              }}
            >
              <BellOff className="h-4 w-4" />
            </HeaderButton>
            <HeaderButton label={t("close")} onClick={() => setOpen(false)}>
              <X className="h-4 w-4" />
            </HeaderButton>
          </header>
          <iframe
            ref={frame}
            title={assistant.name}
            src={`${prefix}${ASSISTANT_FRAME_PATH}?agent=${agentId}`}
            className="min-h-0 w-full flex-1 border-0"
          />
        </div>
      )}

      {speaking && (
        <AssistantBubble
          bubble={bubble}
          proactive={bubble === "approvals" || bubble === "firstSteps"}
          onAsk={ask}
          onSilence={() => setPreferences(readPreferences())}
          path={pathname}
        />
      )}

      <AssistantLauncher
        assistant={assistant}
        agentId={agentId}
        open={open}
        onToggle={() => (open ? setOpen(false) : openWindow())}
      />
    </div>
  );
}

function HeaderButton({
  label,
  onClick,
  pressed,
  children,
}: {
  label: string;
  onClick: () => void;
  pressed?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      onClick={onClick}
      className="text-muted-foreground hover:text-foreground hover:bg-foreground/[0.05] rounded-md p-1.5"
    >
      {children}
    </button>
  );
}
